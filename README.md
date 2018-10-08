# ebs-encrypt
Encrypt the EBS volumes of one or more (or all!) EC2 instances within a particular region in the AWS account, using the default aws ebs key or a specified customer master key (CMK) within the account


        NOTE:
        **This will encrypt all volumes for the EC2,
          including the ROOT volume!

        **If an EC2 instance is running, it will be STOPPED (to ensure disk integrity)
          before its volumes are encrypted

## Python versions:  
This is portable and tested to work for python 2.7+ and 3.4+

## Requirements:
    Will need to ensure boto3 libraries have been installed as part of your Python libraries
    To do so, run  "python -mpip install boto3" on your command line (should work on any OS)
    OR, simply run
    pip install -r requirements.txt

## Parameters: 

### Mandatory:
            -p:  User profile who is running the script (e.g.  -p test-account )
            -r:  the REGION (e.g., -r us-east-2) that is affected.  
                Keep in mind KMS is REGION specific.  This is an anomaly of IAM 
### Optional:
            -k:  the CMK (Master Key) under which the DEKs will be be used to encrypt the volume(s). 
                You can specify the Alias of the Key or the actual Key ID.  Alias is better since it can point to a newer master key in case the old CMK is no longer valid or gets replaced with a newer CMK key ID. 
                IF CMK is NOT Specified, then the default AWS EBS key will be used, which in this case is alias/aws/ebs
            -i : EC2 instance-id's  to be encrypted 
                (e.g. -i i-0f084d152c27f9a5f i-021d3a27a71da28be) 
                for these 2 EC2 instance id's
                NOTE:  If -i is not specified, then ALL EC2 instances in the region will be encrypted!  
                That can take a long time depending on how many instances and how large the volumes are in the region!

## Example:
    python ebs-encrypt.py -p my-aws-test-account -r us-gov-west-1 -i i-0724310a96a022b53
    OR
    python ebs-encrypt.py --profile my-aws-test-account --region us-gov-west-1 --instance-ids i-0724310a96a022b53

### Invocation Help:
    python ebs-encrypt.py --help or -h