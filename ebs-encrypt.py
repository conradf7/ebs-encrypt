"""
Author: Conrad Fernandes

Purpose: Encrypt all volumes attached to (any specified or all) EC2 instances 
        in a specified AWS Region using a specified Master Key (can specify Alias or ID), 
        and run by a specified user (profile) 

        NOTE: This will encrypt all volumes for the EC2,  including the ROOT volume :)

Python program:  This is portable and tested to work using ANY major release of python, 
                    including 2.7+ and 3.4+
Requirements:
    Will need to ensure boto3 libraries have been installed as part of your Python libraries
    To do so, run  "python -mpip install boto3" on your command line (should work on any OS)

PARAMETERS: 

Mandatory:
            -p:  User profile who is running the script (e.g.  -p conrad-test-account )
            -r:  the REGION (e.g., -r us-east-2) that is affected.  
                Keep in mind KMS is REGION specific.  This is an anomaly of IAM 
Optional: 
            -k:  the CMK (Master Key) under which the DEKs will be be used to encrypt the volume(s). 
                You can specify the Alias of the Key or the actual Key ID.  Alias is always better, 
                since it can always point to a newer master key in case the old CMK is toast or 
                goes south for whatever reason, and gets replaced with a newer CMK key ID. 
                IF CMK is NOT Specified, then the default AWS EBS key will be used,
                which in this case is alias/aws/ebs
            -i : EC2 instance-id's  to be encrypted 
                (e.g. -i i-0f084d152c27f9a5f i-021d3a27a71da28be) 
                for these 2 EC2 instance id's

Use ec2crypto --help or -h   for usage            
"""

"""
This script was forked and modified by David Chidester in February 2021 for use at Thermo Fisher Scientific
The following is a summery of changes made:
    - Instance IDs are now reqired for the script to run
    - The ability to encrypt all in an account volumes has been removed

"""
#!/usr/bin/env python 

import logging
import boto3
import botocore
import sys
import argparse
import json
from botocore.exceptions import ClientError


class EBSencrypt(object):
    """ Encrypt EBS volumes from EC2 instance(s) 
    """

    def __init__(self, profile, region, cmk, instance_ids):
        """ Constructor
        profile and region are mandatory inputs
        Also create a logger hander        
            and optionally the CMK and instance-id's to encrypt
            If not provided, will encrypt ALL instances in the region, using the 
            DEFAULT (regional) AWS KMS master key
        """    
        assert (profile != None), "Error: -p profile, needs to be specified"
        assert (region != None), "Error: -r region, needs to be specified"
        assert (instance_ids != None), "Error: -i instance_ids, needs to be specified"
        
        self.region = region 

        # Setup a Debug logger for the session
        self.logger = logging.getLogger('ec2-encrypt')
        self.logger.setLevel(logging.DEBUG)
        self.stream_handler = logging.StreamHandler()
        self.stream_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(self.stream_handler)
        
        # setup:  profile, region
        try:
            self.session = boto3.Session(profile_name=profile, region_name=region)
        except ClientError as e:
            self.logger.error ('Session Problem with AWS Account or Region: {}'.format(e))
            # Major ERROR w account ... bail
            sys.exit(1)

        # Now setup for ec2 instances
        self.ec2_resource = self.session.resource('ec2')
        self.ec2_client = self.session.client('ec2')

        # list instances, based on either incoming ids, or list all ec2's in region 
        self.instances = list()
        try:
            if (instance_ids != None):
                for i in instance_ids:
                    try:
                        ### Validate the Instance Ids provided by user
                        inst_details = self.ec2_client.describe_instances(InstanceIds=[i])
                        if (inst_details is None):
                            msg = ('Error: INST {} does not exist').format(i)
                            self.logger.warning (msg)
                            continue
                    except ClientError as e:
                        self.logger.warning (('{}').format(e))
                        continue

                    inst = self.ec2_resource.Instance(id=i)
                    self.instances.append  (inst)

            assert ( len(self.instances) != 0), "Error: No instances"
        except ClientError as e:
            self.logger.error ('ERROR listing EC2 instances: {}'.format(e))

        #store the master key (under which the encryption / DEKs will take place)
        # use the default regional aws ebs key, in case user didn't specify CMK
        self.cmk=cmk if (cmk != None) else 'alias/aws/ebs'

        """
        TODO  -  Validate the cmk if provided by user 

        """

        # Waiters ... we could use some helpful garcons :) 
        self.waiters = dict()
        try:
            for w in ('snapshot_completed', 'volume_available',
                        'instance_running','instance_stopped' ):
                self.waiters[w] = self.ec2_client.get_waiter(w)

            assert ( len(self.waiters) != 0), (
                "Error: No Waiters ... I can't do my own dishes :(")
        except ClientError as e:
            self.logger.error ('Major ERROR w EC2 client Waiters: {}'.format(e))
            # Bummer. Waiters are critical ... bail
            sys.exit(1)

        #Current instance 
        self.instance = None

        # Volumes
        self.original_snap = None
        self.encrypted_snap = None
        self.new_volume = None

    def cleanup(self, device):
        """ Delete the intermediate snapshots and nuke the old volume
        """
        assert (device != None), "ERROR cleanup: Empty (device) param"

        # Delete intermediaries 
        self.logger.info('->Deleting intermediary snapshots %s and %s', 
            self.original_snap.id, self.encrypted_snap.id)
        self.original_snap.delete()
        self.encrypted_snap.delete()

        # Nuke the old unencryped volume 
        self.logger.info('->Deleting original volume: %s', device.id)
        self.waiters['volume_available'].wait (VolumeIds=[device.id])
        device.delete()
        

    def create_encrypted_volume(self, snapshot, original_device):
        """ Create an encrypted volume from the encrypted snapshot
        """
        assert (snapshot != None), "ERROR create_encrypted_volume: Empty (snapshot) param"
        assert (original_device != None), "ERROR create_encrypted_volume: Empty (original_device) param"

        self.logger.info('->Creating an encrypted volume from %s' % snapshot.id)
        volume = self.ec2_resource.create_volume(
                            SnapshotId=snapshot.id,
                            VolumeType=original_device.volume_type,
                            AvailabilityZone=original_device.availability_zone)
        self.waiters['volume_available'].wait (VolumeIds=[volume.id])

        #restore Tags, if were present 
        if original_device.tags:
            volume.create_tags(Tags=original_device.tags)

        return volume

    def encrypt_snapshot(self, snapshot):
        """ Copy and encrypt a snapshot
        """
        assert (snapshot != None), "ERROR encrypt_snapshot: Empty (snapshot) param"

        self.logger.info('->Copy the snapshot %s and encrypt it using Key: %s' 
                             % (snapshot.id, self.cmk))
        try:
            msg = 'Copy of snapshot %s and encrypted w Key: %s' % (snapshot.id, self.cmk)
            snap_id = snapshot.copy(Description=msg,
                                Encrypted=True, SourceRegion=self.region, 
                                KmsKeyId=self.cmk)
            snapshot = self.ec2_resource.Snapshot(snap_id['SnapshotId'])
            self.waiters['snapshot_completed'].wait (SnapshotIds=[snapshot.id])
        except ClientError as e:
            self.logger.error ('Problem with Snapshot copy: {}'.format(e))

        return snapshot

    def swap_volumes(self, old_volume, new_volume):
        """ Swap the old volume for the new encrypted one
        """
        assert (old_volume != None), "ERROR swap_volumes: Empty (old_volume) param"
        assert (new_volume != None), "ERROR swap_volumes: Empty (new_volume) param"

        self.logger.info('->Swap the old volume for the new one')
        device = old_volume.attachments[0]['Device']
        #detach old
        self.instance.detach_volume(Device=device, VolumeId=old_volume.id)
        self.waiters['volume_available'].wait (VolumeIds=[old_volume.id])
        #attach new encrypted
        self.instance.attach_volume(Device=device, VolumeId=new_volume.id)

        self.logger.info('->New ENCRYPTED attached volume: %s', new_volume.id)

    def take_snapshot(self, device):
        """ First, take a snapshot of the original unencrypted volume
        """
        assert (device != None), "ERROR take_snapshot: No device param"

        self.logger.info('->Taking a snapshot of volume %s ....' % device.id)
        snapshot = device.create_snapshot(Description='snap of %s' % device.id)
        self.waiters['snapshot_completed'].wait (SnapshotIds=[snapshot.id])
        return snapshot

    def stop_instance(self):
        #todo  -- shutdown instance 
        instance = self.instance

        # Only shutting down if instance.state is in Running state (or Code == 16)
        if (instance.state['Name'] == 'running'):
            instance.stop() 
            # wait till stopped ...
            self.logger.info('-->Stopping running instance: %s ... ' % instance.id)
            self.waiters['instance_stopped'].wait (InstanceIds=[instance.id])
            self.logger.info('\t... Stopped')

    def encrypt_instance(self, inst):
        """ Encrypt the instance's volumes """

        assert (inst != None), (
            "Error encrypt_instance: Expecting an instance, but got empty (inst)")
        self.instance = inst

        self.logger.info('Starting work on instance: %s' % self.instance.id)

        # Encrypt only EC2 EBS-backed
        for device in self.instance.block_device_mappings:
            if 'Ebs' not in device:
                msg = ('{0}: Skipping {1} ... not an EBS device'
                        ) .format(self.instance.id, device['VolumeId'])
                self.logger.warning(msg)
                continue

        #Check to see if already encrypted
        for device in self.instance.volumes.all():
            if device.encrypted:
                msg = ('{0.id}: Volume {1.id} already encrypted'
                        ) .format (self.instance, device)
                self.logger.warning(msg)
                continue

            #################################

            #At this point .... we are ready to encrypt !  
            
            #todo -  First, SHUT DOWN instance if running, to be on safe side
            self.stop_instance()

            msg = ('\n{0.id}: VOLUME {1.id}: will be recreated ENCRYPTED, ' 
                    'and the original deleted') .format(self.instance, device)
            self.logger.info(msg)

            # Handle DeleteOnTermination flag
            delete_flag = device.attachments[0]['DeleteOnTermination']
            flag_on = {'DeviceName': device.attachments[0]['Device'],
                       'Ebs': {'DeleteOnTermination':  delete_flag}}

            # First take a snapshot from the original device
            self.original_snap = self.take_snapshot(device)
            # Then, copy this snapshot and encrypt it
            self.encrypted_snap = self.encrypt_snapshot(self.original_snap)
            # Create a new volume from that encrypted snapshot
            self.new_volume = self.create_encrypted_volume(self.encrypted_snap, device)
            # Finally, swap the old-device for the new one
            self.swap_volumes(device, self.new_volume)
            # Don't forget to clean up the intermediary snapshots and old volume
            self.cleanup(device)

            if delete_flag:
                self.logger.info('->Put flag DeleteOnTermination on volume')
                self.instance.modify_attribute(BlockDeviceMappings=[flag_on])

        self.logger.info('Done with instance: %s\n' % self.instance.id)

    def encrypt(self):
        for inst in self.instances:
            self.encrypt_instance(inst)

def main(args):
    """ main function """

    #Perform the Volume encryption using the kms params
    EBSencrypt(args.profile, args.region, args.key, args.instance_ids).encrypt()
    
if __name__ == '__main__':
    description = ('EBSencrypt: Will Encrypt EBS volumes including Root volume \
    on specified EC2 instances. It will also first stop the EC2 instance(s) if running \
    to be on the safe side prior to encrypting the volumes.  \
    PLEASE NOTE: If a particular CMK (Customer Master Key) is not specified, then the \
    default regional AWS (aws/ebs) key will be used')

    parser = argparse.ArgumentParser(description=description)
    #mandatory options
    parser.add_argument('-p', '--profile', help='AWS Profile', required=True)
    parser.add_argument('-r', '--region', help='AWS Region', required=True)
    parser.add_argument('-i', '--instance_ids', nargs='+',
                        help='Instance-IDs to encrypt', required=True)
    #optional options
    parser.add_argument('-k', '--key', help='Customer Master Key', required=False)
    args = parser.parse_args()

    # Call the main function 
    main(args)
    
