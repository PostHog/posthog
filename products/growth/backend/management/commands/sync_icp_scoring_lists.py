from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.growth.backend.facade import api, contracts


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
        try:
            created = api.create_icp_scoring_lists(
                version=version,
                tags_csv=options["tags_csv"],
                investors_csv=options["investors_csv"],
                activate=options["activate"],
            )
        except contracts.ScoringListsRejected as e:
            raise CommandError(str(e)) from e

        state = "active" if created.is_active else "inactive (activate via admin or --activate)"
        self.stdout.write(
            self.style.SUCCESS(
                f"created IcpScoringConfig {version}: {created.tag_rows} tag rows, {created.investor_rows} investors "
                f"({created.investors_with_aliases} with aliases) — {state}"
            )
        )
        self.stdout.write(
            "buckets: "
            + ", ".join(f"{field}={count}" for field, count in created.bucket_counts)
            + f", quality_investors={created.quality_investors}"
        )

        if created.investors_with_aliases == 0:
            self.stdout.write(
                self.style.WARNING(
                    "no investor has any aliases — check whether the aliases column was renamed or dropped"
                )
            )

        if created.unrecognized_tokens:
            total = sum(count for _, count in created.unrecognized_tokens)
            detail = ", ".join(f"{token!r} x{count}" for token, count in created.unrecognized_tokens)
            self.stdout.write(
                self.style.WARNING(f"{total} unrecognized recommendation token(s) dropped from every bucket: {detail}")
            )
