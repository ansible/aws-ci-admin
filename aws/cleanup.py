#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK
"""Terminate or destroy stale resources in the AWS test account."""

import argparse
import logging
import contextlib
import os


try:
    import argcomplete
except ImportError:
    argcomplete = None


from terminator import (
    cleanup,
    get_concrete_subclasses,
    logger,
    Terminator,
)


@contextlib.contextmanager
def update_aws_environ(aws_profile, aws_region, dynamodb_table):
    """
    Temporarily updates the ``os.environ`` dictionary in-place.
    The 'AWS_REGION' will be removed from the os.environ dictionnary and will
    add the 'AWS_PROFILE', 'CLEANUP_AWS_REGION' and 'DYNAMODB_TABLE_NAME' environment variables.
    """
    env = os.environ
    update = {}
    if aws_profile:
        update.update({'AWS_PROFILE': aws_profile})
    if aws_region:
        update.update({'CLEANUP_AWS_REGION': aws_region})
    if dynamodb_table:
        update.update({'DYNAMODB_TABLE_NAME': dynamodb_table})
    to_remove = ["AWS_REGION"]

    # List of environment variables being updated or removed.
    stomped = (set(update.keys()) | set(to_remove)) & set(env.keys())
    # Environment variables and values to restore on exit.
    update_after = {k: env[k] for k in stomped}
    # Environment variables and values to remove on exit.
    remove_after = frozenset(k for k in update if k not in env)

    try:
        env.update(update)
        for k in to_remove:
            env.pop(k, None)
        yield
    finally:
        env.update(update_after)
        for k in remove_after:
            env.pop(k)


def main():
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter('%(name)-12s: %(levelname)-8s %(message)s')

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    logger.addHandler(console)

    args = parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    with update_aws_environ(aws_profile=args.profile, aws_region=args.region, dynamodb_table=args.table_name):
        cleanup(check=args.check, force=args.force, targets=args.target)


def parse_args():
    parser = argparse.ArgumentParser(description='Terminate or destroy stale resources in the AWS account.')

    parser.add_argument('--region',
                        required=True,
                        help='The AWS region from which resources will be terminated')

    parser.add_argument('--profile',
                        required=True,
                        help='The AWS profile')

    parser.add_argument('--table-name',
                        required=True,
                        help='The DynamoDB table name use to track resources lifetime')

    parser.add_argument('-c', '--check',
                        action='store_true',
                        help='do not terminate resources')

    parser.add_argument('-f', '--force',
                        action='store_true',
                        help='do not skip unsupported or stale resources')

    parser.add_argument('-v', '--verbose',
                        action='store_true',
                        help='increase logging verbosity')

    parser.add_argument('--target',
                        choices=sorted([value.__name__ for value in get_concrete_subclasses(Terminator)] + ['Database']),
                        metavar='target',
                        action='append',
                        help='class to run')

    if argcomplete:
        argcomplete.autocomplete(parser)

    args = parser.parse_args()

    return args


if __name__ == '__main__':
    main()
