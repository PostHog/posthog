import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from products.feature_flags.backend.user_blast_radius import get_user_blast_radius_persons
from products.workflows.backend.services.batch_audience import (
    get_batch_audience_count,
    get_batch_audience_person_ids,
    use_workflows_batch_audience_query,
)

FILTERS = {"properties": [{"key": "subscribed", "type": "person", "value": ["true"], "operator": "exact"}]}

COOLDOWN_PROPERTY = "last_workflow_email_sent_at"


def _cooldown_filters(properties_operator: str | None) -> dict:
    filters: dict = {
        "properties": [
            {"key": COOLDOWN_PROPERTY, "type": "person", "operator": "is_not_set", "value": "is_not_set"},
            {"key": COOLDOWN_PROPERTY, "type": "person", "operator": "is_date_before", "value": "-2d"},
        ]
    }
    if properties_operator is not None:
        filters["properties_operator"] = properties_operator
    return filters


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

    def test_count_matches_deduped_audience_size(self):
        self._create_audience(["Dup@X.com", " dup@x.com ", "b@x.com", None, ""])

        count = get_batch_audience_count(self.team, FILTERS, dedupe_key="email")

        assert count == len(get_batch_audience_person_ids(self.team, FILTERS, dedupe_key="email")) == 4

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
        with patch("products.workflows.backend.services.batch_audience.PERSON_BATCH_SIZE", 2):
            for _ in range(10):
                page = get_batch_audience_person_ids(self.team, FILTERS, cursor=cursor, dedupe_key=dedupe_key)
                collected.extend(page)
                if len(page) < 2:
                    break
                cursor = page[-1]

        assert collected == [_uuid(i) for i in expected_indices]

    @parameterized.expand(
        [
            ("defaults_to_matching_every_condition", None, []),
            ("explicit_and_matches_every_condition", "AND", []),
            ("or_matches_either_condition", "OR", [1, 2]),
        ]
    )
    def test_properties_operator_joins_audience_conditions(self, _name, properties_operator, expected_indices):
        # An email cooldown reads "never emailed OR last emailed before the cooldown". Both conditions
        # sit on one property, so AND can never match anyone: an unset value can't also be a date in
        # the past. Only the OR join returns the two people who are eligible to be emailed.
        for i, sent_at in enumerate([None, "2026-01-01T00:00:00Z", "2026-01-10T00:00:00Z"], start=1):
            properties = {"email": f"user-{i}@x.com"}
            if sent_at is not None:
                properties[COOLDOWN_PROPERTY] = sent_at
            _create_person(team=self.team, distinct_ids=[f"user-{i}"], uuid=_uuid(i), properties=properties)
        flush_persons_and_events()

        filters = _cooldown_filters(properties_operator)
        with freeze_time("2026-01-10T12:00:00Z"):
            person_ids = get_batch_audience_person_ids(self.team, filters, dedupe_key="email")
            # The count is what the confirm token signs, so it has to resolve the same audience the
            # send does, not the AND-joined one.
            count = get_batch_audience_count(self.team, filters, dedupe_key="email")

        assert sorted(person_ids) == [_uuid(i) for i in expected_indices]
        assert count == len(expected_indices)

    def test_use_flag_defaults_off_when_feature_enabled_raises(self):
        # Batch sends are a critical path — a Redis/HyperCache blip that makes
        # posthoganalytics.feature_enabled() throw must fall back to the legacy
        # audience query, not 500 the preview endpoint or fail the resolver job.
        with patch(
            "products.workflows.backend.services.batch_audience.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("HyperCache is down"),
        ):
            assert use_workflows_batch_audience_query(self.team) is False
