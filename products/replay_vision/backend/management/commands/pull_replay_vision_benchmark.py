import datetime as dt
from pathlib import Path
from typing import cast

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import boto3

from products.replay_vision.backend.benchmark.layout import BenchmarkLayout
from products.replay_vision.backend.benchmark.local import Tier, pull_version


class Command(BaseCommand):
    help = "Copy a built Replay Vision benchmark version into a local directory for the eval suite"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("version", help="The built version to copy, for example v1.")
        parser.add_argument("--dest", required=True, help="Local directory for the copy.")
        parser.add_argument("--tier", choices=["fast", "full"], default="fast")
        parser.add_argument("--bucket", default=settings.REPLAY_VISION_BENCHMARK_BUCKET)
        parser.add_argument("--prefix", default=settings.REPLAY_VISION_BENCHMARK_PREFIX)

    def handle(self, *args: object, **options: object) -> None:
        if not options["bucket"]:
            raise CommandError("Pass --bucket or set REPLAY_VISION_BENCHMARK_BUCKET")
        layout = BenchmarkLayout(str(options["version"]), bucket=str(options["bucket"]), prefix=str(options["prefix"]))
        # The default credential chain, so AWS_PROFILE picks the account the version lives in.
        tier = cast(Tier, options["tier"])
        record = pull_version(boto3.client("s3"), layout, tier, Path(str(options["dest"])), dt.datetime.now(dt.UTC))
        self.stdout.write(f"Copied {len(record.case_ids)} {record.tier} cases of {record.version} to {options['dest']}")
