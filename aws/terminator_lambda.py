import logging
import os

from terminator import (
    cleanup,
    logger,
)


# noinspection PyUnusedLocal
def lambda_handler(event, context):
    # pylint: disable=unused-argument
    logger.setLevel(logging.INFO)

    api_name = os.environ["API_NAME"]
    cleanup(check=False, force=False, api_name=api_name)
