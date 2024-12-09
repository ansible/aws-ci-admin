# Introduction

[This repository](https://github.com/ansible/aws-ci-admin) is used by the Ansible Cloud Content Team to clean up stale AWS resources. It is based off of the [aws-terminator](https://github.com/mattclay/aws-terminator) repo.

By default, this is configured to delete resources across all regions. The regions are lumped into three groups that are managed with one lambda per group.

# Contributor process

There are two things you may need to do:
1. Update the permissions in the [policy directory](https://github.com/ansible/aws-ci-admin/tree/main/aws/policy) with those needed to clean up the desired resources. Check the existing policies to avoid adding duplicates. When updating the policies, please ensure you keep permissions alphabetically ordered.
2. Add a terminator class in the corresponding file in the [terminator directory](https://github.com/ansible/aws-ci-admin/tree/main/aws/terminator) if you are adding permissions to delete a new type of AWS resource. Skip this step and submit your pull request if you are only adding permissions to modify resources that are already supported.

The rest of this section is about creating and testing your terminator class.

To begin, you need to use the `Terminator` base class or the `DbTerminator` base class. We terminate resources found based on their age. Not all AWS resources return the creation date timestamp so those resources are stored in a database with the time when the terminator class located them and we approximate when to delete them from that.
* If the resource has a creation date timestamp use the Terminator base class.
* If the resource does not have a creation date timestamp use the DbTerminator base class.

Your terminator class requires the following:
* the staticmethod `create`
* the property `name`
* the property `created_time` (only if you are using the Terminator base class)
* the method `terminate`

You can include the property `id` if there is a unique identifier in addition to a human readable name.

The `create` method should return the base class `_create` method called with the credentials to create the client, the class name, the boto3 resource name to create the client, and a function for the client to use. The function should list all the given resources for that resource type.

Here's an example for an EC2 instance terminator class:

```python
class Ec2Instance(Terminator):

    @staticmethod
    def create(credentials):

        def get_instances(client):
            return [i for r in client.describe_instances()['Reservations'] for i in r['Instances']]

        return Terminator._create(credentials, Ec2Instance, 'ec2', get_instances)
```

`self.instance` is an item from the list returned by the base class `_create` method and should be used by the `id`, `name`, and `created_time` properties.

```python
    @property
    def id(self):
        return self.instance['InstanceId']

    @property
    def name(self):
        return self.instance['PrivateDnsName']

    @property
    def created_time(self):
        return self.instance['LaunchTime']
```

The `terminate` method should use self.client to delete the resource.

```python
    def terminate(self):
        self.client.terminate_instances(InstanceIds=[self.id])
```

To test the terminator class with your own account you can use the [cleanup.py](https://github.com/ansible/aws-ci-admin/blob/main/aws/cleanup.py) script.

Warning: Always use the --check (or -c) flag and the --target flag to avoid accidentally deleting wanted resources.
It is safest to use `cleanup.py` in an empty/dev account.

To start using `cleanup.py` you will need to:
* Use Python 3.7+
* Install required python libraries using

      cd aws && pip install -r requirements.txt

* Run `cleanup.py` using the class name as the target to locate the resources in us-east-1:

      python ./cleanup.py --check --region us-east-1 --profile ansible --target Ec2Volume
      cleanup     : DEBUG    located Ec2Volume: count=4
      cleanup     : INFO     [Running in check mode] Would have terminate the resource 'Ec2Volume: name=None, id=vol-06376869027e814e7 age=1125 days, 2:49:05.959000, stale=True'
      cleanup     : INFO     checked Ec2Volume: name=None, id=vol-06376869027e814e7 age=1125 days, 2:49:05.959000, stale=True
      cleanup     : INFO     [Running in check mode] Would have terminate the resource 'Ec2Volume: name=None, id=vol-0174efd26e169da8f age=530 days, 2:36:57.148000, stale=True'
      cleanup     : INFO     checked Ec2Volume: name=None, id=vol-0174efd26e169da8f age=530 days, 2:36:57.148000, stale=True
      cleanup     : INFO     skipped Ec2Volume: name=np0004531895, id=vol-0df9b312014ddf271 age=0:13:58.203000, stale=False
      cleanup     : INFO     [Running in check mode] Would have terminate the resource 'Ec2Volume: name=hebailey-test-bastion, id=vol-041d2eaa4ffdd4c45 age=140 days, 2:25:00.608000, stale=True'
      cleanup     : INFO     checked Ec2Volume: name=hebailey-test-bastion, id=vol-041d2eaa4ffdd4c45 age=140 days, 2:25:00.608000, stale=True


* The class property `age_limit` determines when a resource becomes stale. This is 7 days by default. Once a resource is stale, the terminator can delete it. Use check mode (-c or --check) to see what your class would delete without actually removing it.
* Once a resource is stale you can test that it can be cleaned up by removing the check mode flag.
  For example, `python cleanup.py --region us-east-1 --profile ansible --target Ec2Instance -v`.
* You can forcibly delete resources that are not stale by using --force (or -f). Be aware that this can also remove resources that do not use the Terminator or DbTerminator base classes. Such unsupported resources will not be cleaned up by the CI account.

After you have tested that your terminator class can be used by `cleanup.py`, submit your pull request.


# Deploying to AWS

Deploying to AWS is done using an Ansible playbook [terminator.yml](https://github.com/ansible/aws-ci-admin/blob/main/aws/terminator.yml), which can be easily run with make using the provided Makefile. See the [config.yml file](https://github.com/ansible/aws-ci-admin/blob/main/aws/config.yml) to adjust how the terminator lambdas are deployed. Ensure your AWS profile and credentials are correctly configured before using the Makefile. You will need to have the ansible collections listed in https://github.com/ansible/aws-ci-admin/blob/main/requirements.yml installed.

The initial deployment of the lambdas can be done by running:

```shell
$ make terminator
```

This will create the necessary policies and roles, deploy the lambdas and create a Cloudwatch schedule for the lambdas.

After initial deployment, changes to policies can be deployed with:

```shell
$ make test_policy
```

Changes to the terminator lambda can be deployed with:

```shell
$ make terminator_lambda
```

To deactivate the terminator on the AWS account, use the following command:

```shell
$ make terminator_clean
```
