from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.services import recipient_lists
from products.workflows.backend.services.recipient_lists import (
    RecipientListInvalid,
    RecipientListNotFound,
    create_recipient_list,
    get_recipient_list,
    get_recipient_list_page,
)


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def write(self, key: str, content: str) -> None:
        self.objects[key] = content

    def read(self, key: str, *, missing_ok: bool = False) -> str | None:
        return self.objects.get(key)


class TestRecipientListUpload(SimpleTestCase):
    def setUp(self) -> None:
        self.storage = _MemoryStorage()
        patcher = patch.object(recipient_lists, "object_storage", self.storage)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_keeps_valid_rows_and_counts_dropped_ones(self) -> None:
        rows = [
            {"\ufeffEmail": " ada@example.com ", "Distinct ID": "user-1", "Org Name": "Hedgebox"},
            {"Email": "ADA@example.com", "Org Name": "Duplicate"},
            {"Email": "not-an-email", "Org Name": "Broken"},
            {"Email": "big@example.com", "Org Name": "x" * 5000},
            {"Email": "grace@example.com", "Org Name": "Hogflix", "Destinations": "slack;webhook", "": ""},
        ]

        summary = create_recipient_list(team_id=1, rows=rows)

        assert (summary.row_count, summary.columns) == (2, ["email", "org_name", "destinations"])
        assert (summary.dropped_invalid_email, summary.dropped_duplicate_email, summary.dropped_too_large) == (1, 1, 1)
        assert get_recipient_list(team_id=1, list_id=summary.id) == summary
        assert get_recipient_list(team_id=2, list_id=summary.id) is None

    @parameterized.expand(
        [
            ("no_email_column", [{"name": "Ada"}], 'column named "email"'),
            ("no_valid_email", [{"email": "nope"}], "valid email address"),
            ("too_many_rows", [{"email": "a@example.com"}] * 3, "up to 2"),
            (
                "two_columns_with_one_name",
                [{"email": "a@example.com", "Email ": "b@example.com"}],
                'both named "email"',
            ),
            ("non_ascii_header", [{"email": "a@example.com", "会社": "Hedgebox"}], 'column "会社" needs a name'),
            ("punctuation_header", [{"email": "a@example.com", "!!!": "x"}], 'column "!!!" needs a name'),
        ]
    )
    def test_rejects_unusable_lists(self, _name: str, rows: list[dict[str, str]], message: str) -> None:
        with patch.object(recipient_lists, "MAX_RECIPIENT_LIST_ROWS", 2), pytest.raises(RecipientListInvalid) as error:
            create_recipient_list(team_id=1, rows=rows)
        assert message in str(error.value)

    @parameterized.expand([("not_a_uuid", "../../team-2/x"), ("unknown_list", "01970000-0000-0000-0000-000000000000")])
    def test_missing_list_has_no_rows(self, _name: str, list_id: str) -> None:
        assert get_recipient_list(team_id=1, list_id=list_id) is None
        with pytest.raises(RecipientListNotFound):
            get_recipient_list_page(team_id=1, list_id=list_id, cursor=None)


class TestRecipientListPage(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(recipient_lists, "object_storage", _MemoryStorage())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matches_each_row_to_a_person_and_pages(self) -> None:
        older, newer = "01970000-0000-0000-0000-000000000001", "01970000-0000-0000-0000-000000000002"
        known = "01970000-0000-0000-0000-000000000009"
        _create_person(team=self.team, distinct_ids=["user-1"], uuid=known)
        _create_person(team=self.team, distinct_ids=["a"], uuid=newer, properties={"email": "Grace@Example.com "})
        _create_person(team=self.team, distinct_ids=["b"], uuid=older, properties={"email": "grace@example.com"})
        flush_persons_and_events()
        rows: list[dict[str, Any]] = [
            {"email": "ada@example.com", "distinct_id": "user-1", "org": "Hedgebox"},
            {"email": "grace@example.com", "distinct_id": "no-such-id", "org": "Hogflix"},
            {"email": "nobody@example.com", "org": "Unknown"},
        ]

        with patch.object(recipient_lists, "RECIPIENT_LIST_PAGE_SIZE", 2):
            summary = create_recipient_list(team_id=self.team.id, rows=rows)
            first = get_recipient_list_page(team_id=self.team.id, list_id=summary.id, cursor=None)
            second = get_recipient_list_page(team_id=self.team.id, list_id=summary.id, cursor=first.cursor)

        assert (first.has_more, second.has_more, second.cursor) == (True, False, None)
        matched = [(r.email, r.distinct_id, r.person_id) for r in [*first.recipients, *second.recipients]]
        assert matched == [
            ("ada@example.com", "user-1", known),
            ("grace@example.com", None, older),
            ("nobody@example.com", None, None),
        ]
        assert first.recipients[0].variables == {"email": "ada@example.com", "org": "Hedgebox"}

    def test_matches_a_full_page_of_emails(self) -> None:
        emails = [f"user-{index}@example.com" for index in range(101)]
        for index, email in enumerate(emails):
            _create_person(team=self.team, distinct_ids=[f"id-{index}"], properties={"email": email})
        flush_persons_and_events()

        summary = create_recipient_list(team_id=self.team.id, rows=[{"email": email} for email in emails])
        page = get_recipient_list_page(team_id=self.team.id, list_id=summary.id, cursor=None)

        assert [recipient.email for recipient in page.recipients if recipient.person_id is None] == []
