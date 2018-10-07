# ebs-encrypt
Encrypt the EBS volumes of one or more (or all!) EC2 instances within a particular region in the AWS account, using the default aws ebs key or a specified customer master key (CMK) within the account



        NOTE: This will encrypt all volumes for the EC2,  including the ROOT volume :)

## Python version:  
This is portable and tested to work using ANY major release of python, 
                    including 2.7+ and 3.4+

## Requirements:
    Will need to ensure boto3 libraries have been installed as part of your Python libraries
    To do so, run  "python -mpip install boto3" on your command line (should work on any OS)

## Parameters: 

### Mandatory:
            -p:  User profile who is running the script (e.g.  -p test-account )
            -r:  the REGION (e.g., -r us-east-2) that is affected.  
                Keep in mind KMS is REGION specific.  This is an anomaly of IAM 
### Optional: 
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