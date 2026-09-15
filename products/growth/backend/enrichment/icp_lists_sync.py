"""Load the RevOps ICP scoring list exports (tags + quality investors) into a new IcpScoringConfig row.

Quarterly flow: RevOps edits the two internal sheets, exports them as CSV, and this turns the
exports into a new versioned row — optionally activating it in the same run. A list change is
always a new row; rows are never edited in place, so every stamped `icp_lists_version` in
stored scores stays reconstructable.
"""

import csv
from typing import Any

from django.db import transaction

from products.growth.backend.enrichment.icp_lists import (
    TAG_BUCKETS,
    build_curated_lists,
    clear_lists_cache,
    parse_investors_csv_rows,
    parse_tags_csv_rows,
    unrecognized_recommendation_tokens,
)
from products.growth.backend.facade.contracts import ScoringListsCreated, ScoringListsRejected
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
                raise ScoringListsRejected(f"{path} is missing required columns: {sorted(missing)}")
            return list(reader)
    except OSError as e:
        raise ScoringListsRejected(f"could not read {path}: {e}")


def create_icp_scoring_lists(*, version: str, tags_csv: str, investors_csv: str, activate: bool) -> ScoringListsCreated:
    if IcpScoringConfig.objects.filter(version=version).exists():
        raise ScoringListsRejected(f"IcpScoringConfig version {version!r} already exists; pick a new version")

    tags = parse_tags_csv_rows(_read_csv(tags_csv, TAGS_REQUIRED_COLUMNS))
    investors = parse_investors_csv_rows(_read_csv(investors_csv, INVESTORS_REQUIRED_COLUMNS))
    if not tags:
        raise ScoringListsRejected("tags export parsed to zero rows; refusing to create an empty list version")
    if not investors:
        raise ScoringListsRejected("investors export parsed to zero rows; refusing to create an empty list version")

    curated = build_curated_lists(IcpScoringConfig(version=version, tags=tags, quality_investors=investors))
    bucket_counts = {field: len(getattr(curated, field)) for field in sorted(TAG_BUCKETS)}
    if not any(bucket_counts.values()):
        raise ScoringListsRejected(
            f"tags export for version {version!r} parsed to buckets that are all empty "
            "(vocabulary drift, a wrong delimiter, or a shifted column?); refusing to create it"
        )
    if not curated.quality_investors:
        raise ScoringListsRejected(
            f"investors export for version {version!r} parsed to zero quality investors; refusing to create it"
        )

    with transaction.atomic():
        if activate:
            IcpScoringConfig.objects.filter(is_active=True).update(is_active=False)
        config = IcpScoringConfig.objects.create(
            version=version,
            tags=tags,
            quality_investors=investors,
            is_active=activate,
        )
    clear_lists_cache()

    unrecognized = unrecognized_recommendation_tokens(tags)
    return ScoringListsCreated(
        version=version,
        is_active=config.is_active,
        tag_rows=len(tags),
        investor_rows=len(investors),
        investors_with_aliases=sum(1 for investor in investors if investor["aliases"]),
        bucket_counts=tuple(bucket_counts.items()),
        quality_investors=len(curated.quality_investors),
        unrecognized_tokens=tuple(unrecognized.most_common()),
    )
