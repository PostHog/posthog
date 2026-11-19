import pytest

from products.warehouse_destinations.backend.core.table_marker import TableMarker, is_owned_by, parse
from products.warehouse_destinations.backend.facade.contracts import MergeSpec


@pytest.mark.parametrize(
    "marker",
    [
        TableMarker(),
        TableMarker(owner_tag='tag "with" quotes: and colons'),
        TableMarker(owner_tag="tag", committed_staging_key="run-2"),
        TableMarker(
            owner_tag="tag",
            require_owned=True,
            merge=MergeSpec(primary_keys=("id", "team"), version_keys=("version",), dedupe_source=True),
        ),
    ],
)
def test_marker_round_trips(marker: TableMarker) -> None:
    assert parse(marker.encode()) == marker


@pytest.mark.parametrize(
    "comment",
    [
        None,
        "",
        "someone's table",
        "[1, 2]",
        '{"owner_tag": "tag"}',
        '{"posthog_destination": 2, "owner_tag": "tag"}',
        '{"posthog_destination": 1, "owner_tag": 5}',
        '{"posthog_destination": 1, "merge": {"primary_keys": []}}',
        '{"posthog_destination": 1, "merge": {"primary_keys": "id"}}',
    ],
)
def test_foreign_or_malformed_comments_parse_to_none(comment: str | None) -> None:
    assert parse(comment) is None


@pytest.mark.parametrize(
    "comment, owned",
    [
        (TableMarker(owner_tag="tag").encode(), True),
        (TableMarker(owner_tag="tag", committed_staging_key="run").encode(), True),
        (TableMarker(owner_tag="tag123").encode(), False),
        (TableMarker(owner_tag="tag:child").encode(), False),
        (TableMarker().encode(), False),
        ("tag", True),
        ("tag:child", False),
        ("tag123", False),
        (None, False),
    ],
)
def test_ownership_needs_the_exact_tag(comment: str | None, owned: bool) -> None:
    assert is_owned_by(comment, "tag") is owned
