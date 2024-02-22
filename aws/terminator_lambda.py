import logging
import os

from terminator import (
    cleanup,
    logger,
)


def terminator_small_set():
    value = os.environ.get("TERMINATE_SMALL_SET") or "false"
    return value.lower() in ['true', '1', 'yes']


# noinspection PyUnusedLocal
def lambda_handler(event, context):
    # pylint: disable=unused-argument
    logger.setLevel(logging.INFO)

    targets = []
    if terminator_small_set():
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
