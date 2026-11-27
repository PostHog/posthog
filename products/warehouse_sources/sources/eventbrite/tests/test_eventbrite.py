from datetime import UTC, date, datetime

import pytest

from products.warehouse_sources.sources.eventbrite._config import EventbriteSourceConfig
from products.warehouse_sources.sources.eventbrite.eventbrite import (
    EventbriteResumeConfig,
    _format_changed_since,
    validate_credentials,
)
from products.warehouse_sources.sources.eventbrite.settings import EVENTBRITE_ENDPOINTS
from products.warehouse_sources.sources.eventbrite.source import EventbriteSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


def _driver() -> SourceDriver:
    return SourceDriver(EventbriteSource(), EventbriteSourceConfig(api_token="token"))


def _page(
    data_key: str, items: list[dict[str, str]], *, has_more: bool = False, continuation: str | None = None
) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            data_key: items,
            "pagination": {"has_more_items": has_more, "continuation": continuation},
        }
    )


class TestFormatChangedSince:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format_changed_since(self, value: object, expected: str) -> None:
        assert _format_changed_since(value) == expected


class TestTopLevelPagination:
    def test_follows_continuation_until_has_more_false(self) -> None:
        result = _driver().run(
            "organizations",
            [
                _page("organizations", [{"id": "1"}, {"id": "2"}], has_more=True, continuation="tok2"),
                _page("organizations", [{"id": "3"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.params("continuation") == [None, "tok2"]
        # Checkpoint saved after the first page (points at the next page's token); the last page ends it.
        assert result.saved_states == [EventbriteResumeConfig(continuation="tok2")]

    def test_resume_seeds_continuation(self) -> None:
        result = _driver().run(
            "organizations",
            [_page("organizations", [{"id": "9"}])],
            resume_state=EventbriteResumeConfig(continuation="resume-tok"),
        )

        assert result.raised is None
        assert result.params("continuation") == ["resume-tok"]


class TestIncrementalFilter:
    def test_changed_since_applied_only_to_child_endpoint(self) -> None:
        result = _driver().run(
            "orders",
            [
                _page("organizations", [{"id": "org1"}]),
                _page("orders", [{"id": "ord1"}]),
            ],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="changed",
        )

        assert result.raised is None
        assert result.paths == ["/v3/users/me/organizations/", "/v3/organizations/org1/orders/"]
        assert result.params("changed_since") == [None, "2026-01-01T00:00:00Z"]


class TestFanOutEndpoints:
    @pytest.mark.parametrize(
        "endpoint, parent_pages, expected_paths, expected_params, expected_keys",
        [
            (
                "ticket_groups",
                [_page("organizations", [{"id": "org1"}])],
                ["/v3/users/me/organizations/", "/v3/organizations/org1/ticket_groups/"],
                {"status": [None, "all"]},
                ("id",),
            ),
            (
                "members",
                [_page("organizations", [{"id": "org1"}])],
                ["/v3/users/me/organizations/", "/v3/organizations/org1/members/"],
                {},
                ("_organizations_id", "user_id"),
            ),
            (
                "discounts",
                [
                    _page("organizations", [{"id": "org1"}]),
                    _page("events", [{"id": "ev1", "organization_id": "org7"}]),
                ],
                [
                    "/v3/users/me/organizations/",
                    "/v3/organizations/org1/events/",
                    "/v3/organizations/org7/discounts/",
                ],
                {"scope": [None, None, "event"], "event_id": [None, None, "ev1"]},
                ("_events_id", "id"),
            ),
            (
                "inventory_tiers",
                [
                    _page("organizations", [{"id": "org1"}]),
                    _page("events", [{"id": "ev1", "organization_id": "org1"}]),
                ],
                ["/v3/users/me/organizations/", "/v3/organizations/org1/events/", "/v3/events/ev1/inventory_tiers/"],
                {},
                ("_events_id", "id"),
            ),
        ],
    )
    def test_fan_out_request_and_rows(
        self,
        endpoint: str,
        parent_pages: list[ScriptedResponse],
        expected_paths: list[str],
        expected_params: dict[str, list[str | None]],
        expected_keys: tuple[str, ...],
    ) -> None:
        data_key = EVENTBRITE_ENDPOINTS[endpoint].data_key
        leaf_row = {"id": "row1", "user_id": "user1"}
        result = _driver().run(endpoint, [*parent_pages, _page(data_key, [leaf_row])])

        assert result.raised is None
        assert result.paths == expected_paths
        for name, values in expected_params.items():
            assert result.params(name) == values
        assert result.response is not None
        assert tuple(result.response.primary_keys or []) == expected_keys
        assert len(result.rows) == 1
        assert all(result.rows[0].get(key) is not None for key in expected_keys)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
        ],
    )
    def test_validate_credentials_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("token") is expected

        assert {request.path for request in network.requests_log} == {"/v3/users/me/"}
        assert all(request.headers["authorization"] == "Bearer token" for request in network.requests_log)


class TestEventbriteSourceResponse:
    @pytest.mark.parametrize(
        "endpoint",
        ["categories", "subcategories", "formats", "venues", "ticket_classes", "questions", "canned_questions"],
    )
    def test_non_partitioned_endpoints(self, endpoint: str) -> None:
        response_key = endpoint if endpoint in {"categories", "subcategories", "formats"} else "organizations"
        result = _driver().run(endpoint, [_page(response_key, [])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None
