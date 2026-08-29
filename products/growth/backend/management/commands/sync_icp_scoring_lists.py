"""Load the RevOps ICP scoring list exports (tags + quality investors) into a new IcpScoringConfig row.

Quarterly flow: RevOps edits the two internal sheets, exports them as CSV, and this command
turns the exports into a new versioned row — optionally activating it in the same run.
A list change is always a new row; rows are never edited in place, so every stamped
`icp_lists_version` in stored scores stays reconstructable.
"""

import csv
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from products.growth.backend.enrichment.icp_lists import (
    TAG_BUCKETS,
    build_curated_lists,
    clear_lists_cache,
    parse_investors_csv_rows,
    parse_tags_csv_rows,
    unrecognized_recommendation_tokens,
)
from products.growth.backend.models import IcpScoringConfig

TAGS_REQUIRED_COLUMNS = {"tag", "recommendation"}
INVESTORS_REQUIRED_COLUMNS = {"investor"}


def _read_csv(path: str, required: set[str]) -> list[dict[str, Any]]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing = required - columns
            if missing:
                raise CommandError(f"{path} is missing required columns: {sorted(missing)}")
            return list(reader)
    except OSError as e:
        raise CommandError(f"could not read {path}: {e}")


class Command(BaseCommand):
    help = (
        "Create a new versioned IcpScoringConfig row from the RevOps sheet exports "
        "(tags + quality investors). Never edits an existing row; --activate atomically "
        "moves the active flag to the new row."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tags-csv", required=True, help="Path to the tag-list sheet export")
        parser.add_argument("--investors-csv", required=True, help="Path to the quality-investor sheet export")
        # not --version: that collides with the built-in flag every Django command inherits
        parser.add_argument("--list-version", required=True, help="Version label for the new row, e.g. 2026-08-13")
        parser.add_argument("--activate", action="store_true", help="Make the new row the active one")

    def handle(self, *args: Any, **options: Any) -> None:
        version: str = options["list_version"]
        if IcpScoringConfig.objects.filter(version=version).exists():
            raise CommandError(f"IcpScoringConfig version {version!r} already exists; pick a new version")

        tags = parse_tags_csv_rows(_read_csv(options["tags_csv"], TAGS_REQUIRED_COLUMNS))
        investors = parse_investors_csv_rows(_read_csv(options["investors_csv"], INVESTORS_REQUIRED_COLUMNS))
        if not tags:
            raise CommandError("tags export parsed to zero rows; refusing to create an empty list version")
        if not investors:
            raise CommandError("investors export parsed to zero rows; refusing to create an empty list version")

        curated = build_curated_lists(IcpScoringConfig(version=version, tags=tags, quality_investors=investors))
        bucket_counts = {field: len(getattr(curated, field)) for field in sorted(TAG_BUCKETS)}
        if not any(bucket_counts.values()):
            raise CommandError(
                f"tags export for version {version!r} parsed to buckets that are all empty "
                "(vocabulary drift, a wrong delimiter, or a shifted column?); refusing to create it"
            )
        if not curated.quality_investors:
            raise CommandError(
                f"investors export for version {version!r} parsed to zero quality investors; refusing to create it"
            )

        with transaction.atomic():
            if options["activate"]:
                IcpScoringConfig.objects.filter(is_active=True).update(is_active=False)
            config = IcpScoringConfig.objects.create(
                version=version,
                tags=tags,
                quality_investors=investors,
                is_active=options["activate"],
            )
        clear_lists_cache()

        investors_with_aliases = sum(1 for investor in investors if investor["aliases"])
        state = "active" if config.is_active else "inactive (activate via admin or --activate)"
        self.stdout.write(
            self.style.SUCCESS(
                f"created IcpScoringConfig {version}: {len(tags)} tag rows, {len(investors)} investors "
                f"({investors_with_aliases} with aliases) — {state}"
            )
        )
        self.stdout.write(
            "buckets: "
            + ", ".join(f"{field}={count}" for field, count in bucket_counts.items())
            + f", quality_investors={len(curated.quality_investors)}"
        )

        if investors_with_aliases == 0:
            self.stdout.write(
                self.style.WARNING(
                    "no investor has any aliases — check whether the aliases column was renamed or dropped"
                )
            )

        unrecognized = unrecognized_recommendation_tokens(tags)
        if unrecognized:
            total = sum(unrecognized.values())
            detail = ", ".join(f"{token!r} x{count}" for token, count in unrecognized.most_common())
            self.stdout.write(
                self.style.WARNING(f"{total} unrecognized recommendation token(s) dropped from every bucket: {detail}")
            )
