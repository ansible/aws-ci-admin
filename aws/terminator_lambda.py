import logging
import os

from terminator import (
    cleanup,
    logger,
)


def check_boolean_value(env_name: str) -> bool:
    value = os.environ.get(env_name) or "false"
    return value.lower() in ['true', '1', 'yes']


# noinspection PyUnusedLocal
def lambda_handler(event, context):
    # pylint: disable=unused-argument
    logger.setLevel(logging.INFO)

    targets = []
    if check_boolean_value("TERMINATE_SMALL_SET"):
        targets = [
            "RdsDbCluster",
            "Ec2Volume",
            "Ec2Snapshot",
            "Ec2Instance",
            "Ec2Eip",
            "Ec2NatGateway",
            "Ec2InternetGateway"
        ]

    cleanup(check=False, force=False, targets=targets)
