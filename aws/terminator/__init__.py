import abc
import datetime
import inspect
import json
import logging
import os
import traceback
import typing

from boto3.dynamodb.conditions import Attr
import boto3
import botocore
import botocore.client
import botocore.exceptions
import dateutil.tz

logger = logging.getLogger('cleanup')


T = typing.TypeVar('T')


def get_aws_region():
    return os.environ.get("CLEANUP_AWS_REGION") or "us-east-1"


def log_exception(message: str, *args, level: int = logging.ERROR) -> None:
    payload = {
        "message": (message % args).strip(),
        "traceback": traceback.format_exc().strip(),
    }

    logger.log(level, json.dumps(payload))


def import_plugins() -> None:
    skip_files = ('__init__.py',)
    import_names = [os.path.splitext(name)[0] for name in os.listdir(os.path.dirname(__file__)) if name.endswith('.py') and name not in skip_files]
    for import_name in import_names:
        __import__(f'terminator.{import_name}')


def cleanup(check: bool, force: bool, targets: typing.Optional[typing.List[str]] = None) -> None:
    kvs.domain_name = os.environ.get("DYNAMODB_TABLE_NAME")
    kvs.initialize()

    cleanup_resources(check, force, targets)

    if not targets or 'Database' in targets:
        cleanup_database(check, force)


def process_instance(instance: 'Terminator', check: bool, force: bool = False) -> str:
    if instance.ignore:
        status = 'ignored'
    elif force:
        status = terminate(instance, check)
    elif instance.age is None:
        status = 'unsupported'
    elif instance.stale:
        status = terminate(instance, check)
    else:
        status = 'skipped'
    return status


def cleanup_resources(check: bool, force: bool, targets: typing.Optional[typing.List[str]] = None) -> None:

    if targets:
        targets = [t.lower() for t in targets]
    for terminator_type in sorted(get_concrete_subclasses(Terminator), key=lambda value: value.__name__):
        if targets and terminator_type.__name__.lower() not in targets:
            continue

        # noinspection PyBroadException
        try:
            # noinspection PyUnresolvedReferences
            instances = terminator_type.create()

            for instance in instances:
                status = process_instance(instance, check, force)
                if instance.ignore:
                    logger.debug('%s %s', status, instance)
                else:
                    logger.info('%s %s', status, instance)
        except Exception:  # pylint: disable=broad-except
            log_exception('exception processing resource type: %s', terminator_type)


def cleanup_database(check: bool, force: bool) -> None:
    scan_options = {}

    if not force:
        now = datetime.datetime.utcnow().replace(tzinfo=dateutil.tz.tzutc(), microsecond=0) - datetime.timedelta(minutes=60)
        scan_options['FilterExpression'] = Attr('created_time').lt(now.isoformat())

    scan_options['ProjectionExpression'] = kvs.primary_key
    scan_options['Limit'] = 25
    scan_options['ConsistentRead'] = False

    result = kvs.table.scan(
        **scan_options
    )

    if 'Items' not in result:
        return

    items = result['Items']

    if items and not check:
        with kvs.table.batch_writer():
            for item in items:
                kvs.table.delete_item(Key=item)

    if check:
        status = 'checked'
    else:
        status = 'purged'

    for item in items:
        logger.info('%s database item: %s', status, item['id'])


def terminate(instance: 'Terminator', check: bool) -> str:
    if check:
        logger.info("[Running in check mode] Would have terminate the resource '%s'", instance)
        return 'checked'

    # noinspection PyBroadException
    try:
        instance.terminate()
        instance.cleanup()
    except botocore.exceptions.ClientError as ex:
        error_code = ex.response['Error']['Code']

        if error_code == 'TooManyRequestsException':
            log_exception('error "%s" terminating %s', error_code, instance, level=logging.WARNING)
        else:
            log_exception('error "%s" terminating %s', error_code, instance)
    except Exception:  # pylint: disable=broad-except
        log_exception('exception terminating %s', instance)

    return 'terminated'


def get_concrete_subclasses(class_type: typing.Type[T]) -> typing.Set[typing.Type[T]]:
    subclasses: typing.Set[typing.Type[T]] = set()
    queue: typing.List[typing.Type[T]] = [class_type]

    while queue:
        parent = queue.pop()

        for child in parent.__subclasses__():
            if child not in subclasses:
                queue.append(child)
                if not inspect.isabstract(child):
                    subclasses.add(child)

    return subclasses


def get_account_id() -> str:
    return boto3.client('sts').get_caller_identity().get('Account')


def get_tag_dict_from_tag_list(tag_list: typing.Optional[typing.List[typing.Dict[str, str]]]) -> typing.Dict[str, str]:
    if tag_list is None:
        return {}

    return dict((tag['Key'], tag['Value']) for tag in tag_list)


class Terminator(abc.ABC):
    """Base class for classes which find and terminate AWS resources."""
    _default_vpc = None  # safe as long as executing only within a single region

    def __init__(self, client: botocore.client.BaseClient, instance: typing.Dict[str, typing.Any]):
        self.client = client
        self.instance = instance
        self.now = datetime.datetime.utcnow().replace(tzinfo=dateutil.tz.tzutc(), microsecond=0)

    @staticmethod
    @abc.abstractmethod
    def create() -> typing.List['Terminator']:
        pass

    @property
    def age_limit(self) -> datetime.timedelta:
        return datetime.timedelta(days=7)

    @property
    def id(self) -> typing.Optional[str]:
        return None

    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def created_time(self) -> typing.Optional[datetime.datetime]:
        pass

    @property
    def ignore(self) -> bool:
        return False

    @abc.abstractmethod
    def terminate(self) -> None:
        """Terminate or delete the AWS resource."""

    def cleanup(self) -> None:
        """Cleanup to perform after termination."""

    @property
    def age(self) -> typing.Optional[datetime.timedelta]:
        return self.now - self.created_time if self.created_time else None

    @property
    def stale(self) -> bool:
        return self.age > self.age_limit if self.age else False

    def __str__(self) -> str:
        # noinspection PyBroadException
        try:
            if self.id:
                extra = f'id={self.id} '
            else:
                extra = ''

            return f'{type(self).__name__}: name={self.name}, {extra}age={self.age}, stale={self.stale}'
        except Exception:  # pylint: disable=broad-except
            log_exception('exception converting %s to string', type(self).__name__)
            return type(self).__name__

    @staticmethod
    def _create(instance_type: typing.Type['Terminator'], client_name: str,
                describe_lambda: typing.Callable[[botocore.client.BaseClient], typing.List[typing.Dict[str, typing.Any]]]) -> typing.List['Terminator']:
        client = boto3.client(client_name, region_name=get_aws_region())
        instances = describe_lambda(client)
        terminators = [instance_type(client, instance) for instance in instances]
        logger.debug('located %s: count=%d', instance_type.__name__, len(terminators))

        return terminators

    @property
    def default_vpc(self) -> typing.Dict[str, str]:
        if self._default_vpc is None:
            vpcs = self.client.describe_vpcs(Filters=[{'Name': 'isDefault', 'Values': ['true']}])['Vpcs']

            if vpcs:
                self._default_vpc = vpcs[0]  # found default VPC
            else:
                self._default_vpc = {}  # no default VPC

        return self._default_vpc

    def is_vpc_default(self, vpc_id: str) -> bool:
        return self.default_vpc.get('VpcId') == vpc_id


class DbTerminator(Terminator):
    """Base class for classes which find and terminate AWS resources with age tracked via DynamoDB."""
    def __init__(self, client: botocore.client.BaseClient, instance: typing.Dict[str, typing.Any]):
        super().__init__(client, instance)

        self._kvs_key = None
        self._kvs_value = None
        self._created_time = None

        if self.ignore:
            return

        # noinspection PyBroadException
        try:
            self._kvs_key = f'{type(self).__name__}:{self.id or self.name}'
            self._kvs_value = kvs.get(self._kvs_key)

            if not self._kvs_value:
                self._kvs_value = self.now.isoformat()
                kvs.set(self._kvs_key, self._kvs_value)

            self._created_time = datetime.datetime.strptime(self._kvs_value.replace('+00:00', ''), '%Y-%m-%dT%H:%M:%S').replace(tzinfo=dateutil.tz.tzutc())
        except Exception:  # pylint: disable=broad-except
            log_exception('exception accessing key/value store: %s', self)

    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass

    @property
    def created_time(self) -> typing.Optional[datetime.datetime]:
        return self._created_time

    @abc.abstractmethod
    def terminate(self) -> None:
        """Terminate or delete the AWS resource."""

    def cleanup(self) -> None:
        """Cleanup to perform after termination."""
        if not self._kvs_key or not self._kvs_value:
            logger.warning('skipping cleanup due to missing key/value data: %s', self)
            return

        kvs.delete(self._kvs_key)


class KeyValueStore:
    """ DynamoDB data store for the AWS terminator """
    def __init__(self, domain_name: typing.Optional[str] = None):
        self.ddb = None
        self.domain_name = domain_name
        self.table = None
        self.primary_key = 'id'
        self.initialized = False

    def initialize(self) -> None:
        """Deferred initialization of the DynamoDB database."""
        if self.initialized:
            return

        self.ddb = boto3.resource('dynamodb', region_name=get_aws_region())

        try:
            self.table = self.ddb.Table(self.domain_name)
            if self.table.table_status == 'DELETING':
                self.table.wait_until_not_exists()
                self.create_table()
        except botocore.exceptions.ClientError as ex:
            if ex.response['Error']['Code'] == 'ResourceNotFoundException':
                self.create_table()
            else:
                raise ex

        self.initialized = True

    def get(self, key: str) -> str:
        self.initialize()

        item = self.table.get_item(
            Key={self.primary_key: key},
            ProjectionExpression='created_time',
        ).get('Item', {})

        return item.get('created_time')

    def set(self, key: str, value: str) -> None:
        self.initialize()

        # Don't replace an existing entry
        expression = Attr(self.primary_key).ne(key)

        attributes = {
            self.primary_key: key,
            'created_time': value,
        }

        self.table.put_item(
            Item=attributes,
            ConditionExpression=expression,
        )

    def create_table(self) -> None:
        """Creates a new DynamoDB database."""
        self.table = self.ddb.create_table(
            TableName=self.domain_name,
            AttributeDefinitions=[{
                'AttributeName': self.primary_key,
                'AttributeType': 'S'
            }],
            KeySchema=[{
                'AttributeName': self.primary_key,
                'KeyType': 'HASH'
            }],
            BillingMode='PAY_PER_REQUEST',
        )
        self.table.wait_until_exists()

    def delete(self, key: str) -> None:
        self.initialize()

        self.table.delete_item(
            Key={
                self.primary_key: key
            },
        )


import_plugins()

kvs = KeyValueStore()
