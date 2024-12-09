import logging

from terminator import (
    cleanup,
    logger,
)


# noinspection PyUnusedLocal
def lambda_handler(event, context):
    # pylint: disable=unused-argument
    logger.setLevel(logging.INFO)

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
