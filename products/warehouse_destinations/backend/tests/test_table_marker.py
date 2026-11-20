import pytest

from products.warehouse_destinations.backend.core.table_marker import encode, is_tagged_with, parse


@pytest.mark.parametrize("owner_tag", ["tag", 'tag "with" quotes: and colons', "{}"])
def test_owner_tag_round_trips(owner_tag: str) -> None:
    assert parse(encode(owner_tag)) == owner_tag


@pytest.mark.parametrize(
    "comment",
    [
        # Not tagged.
        None,
        "",
        "someone's table",
        "[1, 2]",
        '{"owner_tag": "tag"}',
        # Malformed.
        '{"posthog_destination": 2, "owner_tag": "tag"}',
        '{"posthog_destination": 1, "owner_tag": 5}',
        '{"posthog_destination": 1}',
    ],
)
def test_untagged_or_malformed_comments_parse_to_none(comment: str | None) -> None:
    assert parse(comment) is None


@pytest.mark.parametrize(
    "comment, tagged",
    [
        (encode("tag"), True),
        (encode("tag123"), False),
        (encode("tag:child"), False),
        ('{"posthog_destination": 2, "owner_tag": "tag"}', False),
        ("tag", True),
        ("tag:child", False),
        ("tag123", False),
        (None, False),
    ],
)
def test_ownership_needs_the_exact_tag(comment: str | None, tagged: bool) -> None:
    assert is_tagged_with(comment, "tag") is tagged
