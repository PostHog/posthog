"""Replay exception events that a suppression rule dropped, from the main error tracking ingestion lane.

The command reads the main ingestion topic between two Kafka message timestamps, keeps the
exceptions of one project that match every --property filter, and produces them back to the same
topic. Fix or remove the suppression rule first, or the pipeline drops the replayed events again.

Choose a window in which none of the matching events were ingested. The replay does not check
ClickHouse, so a matching event that was ingested normally is ingested a second time.

Usage:
    # Dry run (default): print the offset range of each partition and count the matching events
    python manage.py replay_suppressed_error_tracking_exceptions \\
        --team-id 2 --start 2026-01-10T09:00:00+00:00 --end 2026-01-12T11:30:00+00:00 \\
        --property service=checkout

    # Live run: produce the matching events back to the topic
    python manage.py replay_suppressed_error_tracking_exceptions ... --live-run

A live run commits its progress to a consumer group derived from the window and the filters, so
the same command resumes after an interruption instead of replaying from the start.
"""

from __future__ import annotations

import signal
from argparse import ArgumentParser, ArgumentTypeError
from datetime import datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.kafka_client.profiles import KafkaClusterProfile
from posthog.kafka_client.routing import get_profile_settings
from posthog.kafka_client.topics import KAFKA_ERROR_TRACKING_INGESTION
from posthog.models import Team

from products.error_tracking.backend.logic.suppressed_exception_replay import (
    ReplayCriteria,
    ReplayWindow,
    SuppressedExceptionReplayer,
    build_replay_consumer,
    build_replay_producer,
    default_group_id,
)


def _parse_timestamp(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise ArgumentTypeError(f"{raw!r} is not an ISO 8601 timestamp.") from error
    if parsed.tzinfo is None:
        raise ArgumentTypeError(f"{raw!r} has no UTC offset. Add one, for example +00:00.")
    return parsed


def _parse_property(raw: str) -> tuple[str, str]:
    key, separator, value = raw.partition("=")
    if not separator or not key:
        raise ArgumentTypeError(f"{raw!r} is not in KEY=VALUE form.")
    return key, value


class Command(BaseCommand):
    help = "Replay exception events that a suppression rule dropped, from the main error tracking ingestion lane."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Project whose exceptions to replay.")
        parser.add_argument(
            "--start",
            type=_parse_timestamp,
            required=True,
            help="Replay messages that capture produced at or after this ISO 8601 timestamp.",
        )
        parser.add_argument(
            "--end",
            type=_parse_timestamp,
            required=True,
            help="Replay messages that capture produced before this ISO 8601 timestamp.",
        )
        parser.add_argument(
            "--property",
            dest="properties",
            type=_parse_property,
            action="append",
            required=True,
            metavar="KEY=VALUE",
            help="Event property an exception must have to be replayed. Repeat it to require several.",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Produce the matching events. The default is a dry run that only counts them.",
        )
        parser.add_argument("--topic", default=KAFKA_ERROR_TRACKING_INGESTION, help="Topic to read and produce to.")
        parser.add_argument(
            "--profile",
            choices=[profile.value for profile in KafkaClusterProfile],
            default=KafkaClusterProfile.DEFAULT.value,
            help="Kafka cluster profile that provides the brokers and credentials.",
        )
        parser.add_argument("--bootstrap-servers", default=None, help="Brokers to use instead of the profile's.")
        parser.add_argument(
            "--security-protocol", default=None, help="Security protocol to use instead of the profile's."
        )
        parser.add_argument(
            "--group-id",
            default=None,
            help="Consumer group that stores the progress. The default is derived from the window and the filters.",
        )
        parser.add_argument("--batch-size", type=int, default=500, help="Messages to consume per poll.")
        parser.add_argument(
            "--max-message-bytes",
            type=int,
            default=None,
            help="Largest record to produce, in bytes. The default is the profile's producer limit.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            window = ReplayWindow(start=options["start"], end=options["end"])
        except ValueError as error:
            raise CommandError(str(error)) from error
        try:
            team = Team.objects.get(pk=options["team_id"])
        except Team.DoesNotExist as error:
            raise CommandError(f"Project {options['team_id']} does not exist.") from error
        criteria = ReplayCriteria(token=team.api_token, properties=dict(options["properties"]))

        live_run: bool = options["live_run"]
        topic: str = options["topic"]
        group_id: str = options["group_id"] or default_group_id(window=window, criteria=criteria)
        profile = get_profile_settings(profile=KafkaClusterProfile(options["profile"]))

        stop_requested = {"value": False}

        def request_stop(_signum: int, _frame: Any) -> None:
            stop_requested["value"] = True

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)

        consumer = build_replay_consumer(
            profile=profile,
            group_id=group_id,
            bootstrap_servers=options["bootstrap_servers"],
            security_protocol=options["security_protocol"],
        )
        producer = (
            build_replay_producer(
                profile=profile,
                bootstrap_servers=options["bootstrap_servers"],
                security_protocol=options["security_protocol"],
                max_message_bytes=options["max_message_bytes"],
            )
            if live_run
            else None
        )
        replayer = SuppressedExceptionReplayer(
            consumer=consumer,
            producer=producer,
            topic=topic,
            criteria=criteria,
            batch_size=options["batch_size"],
            should_stop=lambda: stop_requested["value"],
            log=lambda message: self.stdout.write(message),
        )

        try:
            try:
                ranges = replayer.plan(window)
            except ValueError as error:
                raise CommandError(str(error)) from error
            self.stdout.write(
                f"{'LIVE' if live_run else 'DRY-RUN'}: topic {topic}, group {group_id}, "
                f"{len(ranges)} partition(s) with messages to read"
            )
            for partition_range in ranges:
                self.stdout.write(
                    f"  partition {partition_range.partition}: "
                    f"offsets {partition_range.start_offset} to {partition_range.end_offset}"
                )
            result = replayer.run(ranges)
        finally:
            consumer.close()
            if producer is not None:
                producer.flush()

        verb = "Replayed" if live_run else "Would replay"
        counts = (
            f"{verb} {result.replayed} of {result.scanned} scanned message(s); "
            f"{result.unparseable} unparseable, {result.errors} error(s)"
        )
        if not result.complete:
            raise CommandError(f"{counts}. The window is not fully read, so rerun the same command to resume.")
        self.stdout.write(self.style.SUCCESS(counts))
