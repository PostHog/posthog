import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from products.feature_flags.backend.user_blast_radius import PERSON_BATCH_SIZE, get_user_blast_radius_persons
from products.workflows.backend.services.batch_audience import (
    audience_page_size,
    get_batch_audience_count,
    get_batch_audience_person_ids,
)

FILTERS = {"properties": [{"key": "subscribed", "type": "person", "value": ["true"], "operator": "exact"}]}


def _uuid(index: int) -> str:
    # Only the last digit differs, so string ordering and ClickHouse UUID ordering agree.
    return f"01970000-0000-0000-0000-00000000000{index}"


class TestBatchAudience(ClickhouseTestMixin, BaseTest):
    def _create_audience(self, emails: list[str | None]) -> list[str]:
        person_ids = []
        for i, email in enumerate(emails, start=1):
            properties: dict = {"subscribed": "true"}
            if email is not None:
                properties["email"] = email
            _create_person(team=self.team, distinct_ids=[f"user-{i}"], uuid=_uuid(i), properties=properties)
            person_ids.append(_uuid(i))
        flush_persons_and_events()
        return person_ids

    @parameterized.expand(
        [
            # Duplicate emails (case/whitespace variants) collapse to the smallest UUID;
            # persons without an email (missing or empty) each keep their own entry.
            ("email_dedupe", "email", [1, 3, 4, 5]),
            ("no_dedupe", None, [1, 2, 3, 4, 5]),
        ]
    )
    def test_audience_dedupe_by_email(self, _name, dedupe_key, expected_indices):
        self._create_audience(["Dup@X.com", " dup@x.com ", "b@x.com", None, ""])

        result = get_batch_audience_person_ids(self.team, FILTERS, dedupe_key=dedupe_key)

        assert sorted(result) == [_uuid(i) for i in expected_indices]

    @parameterized.expand(
        [("enabled", True, False, 2), ("disabled", False, False, None), ("flag_error", False, True, None)]
    )
    def test_count_matches_deduped_audience_size(
        self, _name: str, enabled: bool, flag_error: bool, expected_without_email: int | None
    ) -> None:
        self._create_audience(["Dup@X.com", " dup@x.com ", "b@x.com", None, ""])

        def evaluate_flag(flag_key: str, *_args: object, **_kwargs: object) -> bool:
            if flag_key != "workflows-missing-email-warning":
                return False
            if flag_error:
                raise RuntimeError("Flag evaluation unavailable")
            return enabled

        with patch(
            "posthog.cdp.flag_gated_templates.posthoganalytics.feature_enabled",
            side_effect=evaluate_flag,
        ):
            count = get_batch_audience_count(self.team, FILTERS, dedupe_key="email")

        assert count.sends == len(get_batch_audience_person_ids(self.team, FILTERS, dedupe_key="email")) == 4
        assert count.without_email == expected_without_email

    def test_count_rejects_unsupported_dedupe_key(self):
        # Defence-in-depth: the endpoint's serializer allowlist is the primary gate, but this
        # raise forces a future maintainer adding a new supported key to teach the count
        # function about it too, rather than silently returning email-deduped counts.
        with pytest.raises(ValueError, match="Unsupported dedupe_key"):
            get_batch_audience_count(self.team, FILTERS, dedupe_key="sms")

    def test_audience_without_dedupe_matches_legacy_query(self):
        self._create_audience(["a@x.com", "a@x.com", "b@x.com", None])

        assert sorted(get_batch_audience_person_ids(self.team, FILTERS)) == sorted(
            get_user_blast_radius_persons(self.team, FILTERS)
        )

    @parameterized.expand(
        [
            ("email_dedupe", "email", [1, 2, 3, 5]),
            ("no_dedupe", None, [1, 2, 3, 4, 5]),
        ]
    )
    def test_pagination_emits_each_email_exactly_once(self, _name, dedupe_key, expected_indices):
        # Person 4 duplicates person 1's email but sorts onto a later page — if the cursor
        # were applied inside the aggregation, min(id) would be recomputed per page and
        # a@x.com would be emitted twice.
        self._create_audience(["a@x.com", "b@x.com", "c@x.com", "a@x.com", None])

        collected: list[str] = []
        cursor = None
        with override_settings(WORKFLOWS_PERSON_BATCH_SIZE=2):
            for _ in range(10):
                page = get_batch_audience_person_ids(self.team, FILTERS, cursor=cursor, dedupe_key=dedupe_key)
                collected.extend(page)
                if len(page) < 2:
                    break
                cursor = page[-1]

        assert collected == [_uuid(i) for i in expected_indices]

    @override_settings(WORKFLOWS_PERSON_BATCH_SIZE=7)
    def test_has_more_page_size_follows_the_audience_kind(self):
        # A group audience pages through the flags-owned query with its own limit; comparing its
        # page length against the person setting would stop after the first page.
        assert audience_page_size(None) == 7
        assert audience_page_size(0) == PERSON_BATCH_SIZE
