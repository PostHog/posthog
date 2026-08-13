import json
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONLinkPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zendesk import (
    ZendeskSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.settings import (
    CURSOR_PAGE_SIZE,
    FANOUT_PARENTS,
    INCREMENTAL_ENDPOINTS,
    INCREMENTAL_FIELDS,
    TICKET_COMMENTS_PARENT_NAME,
    ZENDESK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source import ZendeskSource
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.zendesk import (
    ZendeskAfterUrlPaginator,
    ZendeskCursorIncrementalPaginator,
    ZendeskIncrementalEndpointPaginator,
    get_declarative_resource,
    get_resource,
    normalize_subdomain,
    to_zendesk_iso8601,
    to_zendesk_start_time,
    zendesk_source,
)


def _make_response(json_body: dict[str, Any] | None = None) -> Response:
    resp = Response()
    resp.status_code = 200
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _endpoint(resource: Any) -> dict[str, Any]:
    # resource["endpoint"] is typed Optional[str | Endpoint]; narrow it for key access.
    return cast(dict[str, Any], resource["endpoint"])


class TestZendeskValidateCredentials:
    def _config(self) -> ZendeskSourceConfig:
        return ZendeskSourceConfig(subdomain="nibbles", api_key="token", email_address="user@example.com")

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source.validate_credentials",
        return_value=False,
    )
    def test_rejected_credentials_message_names_each_credential(self, _mock_validate) -> None:
        valid, error = ZendeskSource().validate_credentials(self._config(), team_id=1)

        assert not valid
        assert error is not None
        assert "subdomain" in error
        assert "email address" in error
        assert "API token" in error

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source.validate_credentials",
        return_value=True,
    )
    def test_accepts_valid_credentials(self, _mock_validate) -> None:
        assert ZendeskSource().validate_credentials(self._config(), team_id=1) == (True, None)


class TestNormalizeSubdomain:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            pytest.param("nibbles", "nibbles", id="bare_subdomain"),
            pytest.param("nibbles.zendesk.com", "nibbles", id="full_host"),
            pytest.param("https://nibbles.zendesk.com", "nibbles", id="https_url"),
            pytest.param("https://nibbles.zendesk.com/", "nibbles", id="https_url_trailing_slash"),
            pytest.param("http://nibbles.zendesk.com/api/v2", "nibbles", id="url_with_path"),
            pytest.param("  nibbles.zendesk.com  ", "nibbles", id="whitespace"),
            pytest.param("nibbles.ZENDESK.com", "nibbles", id="mixed_case_host"),
            pytest.param("multi-word-team", "multi-word-team", id="hyphenated_subdomain"),
        ],
    )
    def test_collapses_to_subdomain_label(self, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    def test_full_host_does_not_double_when_building_base_url(self) -> None:
        # Regression: a pasted full host previously produced "nibbles.zendesk.com.zendesk.com",
        # whose TLS handshake the Zendesk edge rejects.
        assert f"https://{normalize_subdomain('nibbles.zendesk.com')}.zendesk.com/" == "https://nibbles.zendesk.com/"


class TestZendeskCursorIncrementalPaginator:
    def test_advances_to_next_cursor(self) -> None:
        p = ZendeskCursorIncrementalPaginator()
        resp = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})

        p.update_state(resp)

        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}
        p.update_request(req)

        assert req.params["cursor"] == "abc123"
        # The seed start_time is dropped once we paginate by cursor.
        assert "start_time" not in req.params
        assert req.params["per_page"] == 1000

    def test_first_request_keeps_seed_start_time(self) -> None:
        p = ZendeskCursorIncrementalPaginator()

        # Before any response, has_next_page is True and no cursor is set, so the
        # first request must go out untouched (with its seed start_time).
        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}
        p.init_request(req)

        assert req.params["start_time"] == 1591394586
        assert "cursor" not in req.params

    def test_works_for_any_data_key(self) -> None:
        # The paginator only reads top-level after_cursor/end_of_stream, so the users
        # cursor export (data key "users") paginates identically to tickets.
        p = ZendeskCursorIncrementalPaginator()
        p.update_state(_make_response({"users": [{"id": 1}], "after_cursor": "u1", "end_of_stream": False}))
        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/users/cursor")
        req.params = {"per_page": 1000, "start_time": 0}
        p.update_request(req)
        assert req.params["cursor"] == "u1"
        # The seed start_time must be dropped once we paginate by cursor, same as tickets.
        assert "start_time" not in req.params

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"tickets": [], "after_cursor": "abc123", "end_of_stream": True}, id="end_of_stream"),
            pytest.param({}, id="empty_response"),
        ],
    )
    def test_stops_pagination(self, body: dict[str, Any]) -> None:
        p = ZendeskCursorIncrementalPaginator()

        p.update_state(_make_response(body))

        assert p.has_next_page is False

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"tickets": [{"id": 1}], "after_cursor": None, "end_of_stream": False}, id="missing_cursor"),
            pytest.param({"tickets": [{"id": 1}], "after_cursor": "abc123"}, id="missing_end_of_stream"),
        ],
    )
    def test_raises_on_invalid_response(self, body: dict[str, Any]) -> None:
        p = ZendeskCursorIncrementalPaginator()

        with pytest.raises(ValueError):
            p.update_state(_make_response(body))

    def test_raises_when_cursor_does_not_advance(self) -> None:
        """A cursor that never moves while end_of_stream is False is the time-based
        export's failure mode; fail loud so the activity retries instead of
        silently truncating data."""
        p = ZendeskCursorIncrementalPaginator()

        first = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})
        p.update_state(first)
        assert p.has_next_page is True

        repeated = _make_response({"tickets": [{"id": 1}], "after_cursor": "abc123", "end_of_stream": False})
        with pytest.raises(ValueError):
            p.update_state(repeated)

    def test_paginates_across_multiple_pages(self) -> None:
        p = ZendeskCursorIncrementalPaginator()
        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/tickets/cursor")
        req.params = {"per_page": 1000, "start_time": 1591394586}

        p.update_state(_make_response({"tickets": [{"id": 1}], "after_cursor": "cursor_1", "end_of_stream": False}))
        p.update_request(req)
        assert req.params["cursor"] == "cursor_1"

        p.update_state(_make_response({"tickets": [{"id": 2}], "after_cursor": "cursor_2", "end_of_stream": False}))
        p.update_request(req)
        assert req.params["cursor"] == "cursor_2"

        p.update_state(_make_response({"tickets": [{"id": 3}], "after_cursor": "cursor_3", "end_of_stream": True}))
        assert p.has_next_page is False


class TestZendeskIncrementalEndpointPaginator:
    def test_advances_to_next_page(self) -> None:
        p = ZendeskIncrementalEndpointPaginator()
        p.update_state(_make_response({"end_of_stream": False, "next_page": "https://x.zendesk.com/next"}))

        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/incremental/organizations")
        req.params = {"per_page": 1000, "start_time": 0}
        p.update_request(req)
        assert req.url == "https://x.zendesk.com/next"
        # next_page is a full URL carrying its own query string, so existing params are cleared.
        assert req.params == {}

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"end_of_stream": True, "next_page": None}, id="end_of_stream"),
            pytest.param({}, id="empty_response"),
        ],
    )
    def test_stops_pagination(self, body: dict[str, Any]) -> None:
        p = ZendeskIncrementalEndpointPaginator()

        p.update_state(_make_response(body))

        assert p.has_next_page is False

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"organizations": [{"id": 1}]}, id="missing_end_of_stream"),
            pytest.param({"end_of_stream": False, "next_page": None}, id="missing_next_page"),
        ],
    )
    def test_raises_on_invalid_response(self, body: dict[str, Any]) -> None:
        # organizations now routes through this paginator, so a malformed time-based export
        # response must fail loud (retryable) rather than raise an uncaught KeyError.
        p = ZendeskIncrementalEndpointPaginator()

        with pytest.raises(ValueError):
            p.update_state(_make_response(body))


class TestToZendeskStartTime:
    @pytest.mark.parametrize(
        "value,expected",
        [
            pytest.param(0, 0, id="initial_value_zero"),
            pytest.param(1591394586, 1591394586, id="passthrough_int"),
            pytest.param(datetime(2020, 6, 5, 21, 23, 6, tzinfo=UTC), 1591392186, id="aware_datetime"),
            # Naive datetimes are interpreted as UTC.
            pytest.param(datetime(2020, 6, 5, 21, 23, 6), 1591392186, id="naive_datetime_as_utc"),
        ],
    )
    def test_converts_to_unix_epoch(self, value: Any, expected: int) -> None:
        assert to_zendesk_start_time(value) == expected


class TestIncrementalResourceWiring:
    """The four endpoints that have a Zendesk Incremental Export API must declare a server-side
    `start_time` cursor so incremental sync actually filters data, not just flips write disposition."""

    @pytest.mark.parametrize(
        "endpoint,expected_path,expected_paginator,cursor_path,expected_include",
        [
            pytest.param(
                "users",
                "/api/v2/incremental/users/cursor",
                ZendeskCursorIncrementalPaginator,
                "updated_at",
                None,
                id="users",
            ),
            pytest.param(
                "organizations",
                "/api/v2/incremental/organizations",
                ZendeskIncrementalEndpointPaginator,
                "updated_at",
                None,
                id="organizations",
            ),
            pytest.param(
                "ticket_events",
                "/api/v2/incremental/ticket_events",
                ZendeskIncrementalEndpointPaginator,
                "created_at",
                "comment_events",
                id="ticket_events",
            ),
            pytest.param(
                "ticket_metric_events",
                "/api/v2/incremental/ticket_metric_events",
                ZendeskIncrementalEndpointPaginator,
                "time",
                None,
                id="ticket_metric_events",
            ),
        ],
    )
    def test_endpoint_declares_incremental_start_time(
        self,
        endpoint: str,
        expected_path: str,
        expected_paginator: type,
        cursor_path: str,
        expected_include: str | None,
    ) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        endpoint_config = _endpoint(resource)

        assert endpoint_config["path"] == expected_path
        assert isinstance(endpoint_config["paginator"], expected_paginator)
        # Without include=comment_events the ticket_events export strips comment bodies from
        # child_events — assert the sideload stays wired.
        assert endpoint_config["params"].get("include") == expected_include

        start_time = endpoint_config["params"]["start_time"]
        assert start_time["type"] == "incremental"
        assert start_time["cursor_path"] == cursor_path
        assert start_time["initial_value"] == 0
        # Datetime cursors must convert to the Unix epoch Zendesk expects.
        assert start_time["convert"] is to_zendesk_start_time

    @pytest.mark.parametrize("endpoint", ["users", "organizations", "ticket_events", "ticket_metric_events"])
    def test_write_disposition_follows_incremental_flag(self, endpoint: str) -> None:
        incremental = get_resource(endpoint, should_use_incremental_field=True)
        full_refresh = get_resource(endpoint, should_use_incremental_field=False)

        assert incremental["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert full_refresh["write_disposition"] == "replace"

    def test_incremental_fields_cover_incremental_endpoints(self) -> None:
        # Every endpoint advertised as incremental must declare its incremental field(s).
        for endpoint in INCREMENTAL_ENDPOINTS:
            assert INCREMENTAL_FIELDS.get(endpoint), (
                f"{endpoint} is in INCREMENTAL_ENDPOINTS but has no incremental field"
            )


def _source_inputs(schema_name: str, should_use_incremental_field: bool = False) -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-1",
        source_id="source-1",
        team_id=1,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-1",
        logger=MagicMock(),
        reset_pipeline=False,
    )


# Path + data key for every declaratively configured endpoint, transcribed from Zendesk's
# published OpenAPI description. A drifted path 404s and a drifted data key syncs 0 rows, and
# neither shows up until a customer's sync breaks — so they are pinned here rather than read
# back out of the config under test.
EXPECTED_ENDPOINTS: dict[str, tuple[str, str]] = {
    "satisfaction_ratings": ("/api/v2/satisfaction_ratings", "satisfaction_ratings"),
    "ticket_metrics": ("/api/v2/ticket_metrics", "ticket_metrics"),
    "ticket_audits": ("/api/v2/ticket_audits", "audits"),
    "ticket_comments": ("/api/v2/tickets/{ticket_id}/comments", "comments"),
    "group_memberships": ("/api/v2/group_memberships", "group_memberships"),
    "organization_memberships": ("/api/v2/organization_memberships", "organization_memberships"),
    "macros": ("/api/v2/macros", "macros"),
    "views": ("/api/v2/views", "views"),
    "triggers": ("/api/v2/triggers", "triggers"),
    "automations": ("/api/v2/automations", "automations"),
    "custom_roles": ("/api/v2/custom_roles", "custom_roles"),
    "user_fields": ("/api/v2/user_fields", "user_fields"),
    "organization_fields": ("/api/v2/organization_fields", "organization_fields"),
    "ticket_forms": ("/api/v2/ticket_forms", "ticket_forms"),
    "custom_statuses": ("/api/v2/custom_statuses", "custom_statuses"),
    "tags": ("/api/v2/tags", "tags"),
    "custom_objects": ("/api/v2/custom_objects", "custom_objects"),
    "audit_logs": ("/api/v2/audit_logs", "audit_logs"),
    "activities": ("/api/v2/activities", "activities"),
    "requests": ("/api/v2/requests", "requests"),
    "suspended_tickets": ("/api/v2/suspended_tickets", "suspended_tickets"),
    "deleted_tickets": ("/api/v2/deleted_tickets", "deleted_tickets"),
    "saved_searches": ("/api/v2/saved_searches", "saved_searches"),
    "queues": ("/api/v2/queues", "queues"),
    "brand_agents": ("/api/v2/brand_agents", "brand_agents"),
}

# Endpoints Zendesk returns as one unpaginated collection — sending `page[size]` there would be
# an undocumented param.
UNPAGINATED_ENDPOINTS = {"custom_roles", "custom_statuses", "custom_objects", "saved_searches", "queues"}


class TestZendeskDeclarativeEndpoints:
    def test_catalog_matches_the_published_api(self) -> None:
        assert {name: (c.path, c.data_selector) for name, c in ZENDESK_ENDPOINTS.items()} == EXPECTED_ENDPOINTS

    @pytest.mark.parametrize("endpoint", sorted(set(EXPECTED_ENDPOINTS) - {"ticket_comments"}))
    def test_resource_wiring(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        endpoint_config = _endpoint(resource)
        path, data_selector = EXPECTED_ENDPOINTS[endpoint]

        assert resource["name"] == endpoint
        assert endpoint_config["path"] == path
        assert endpoint_config["data_selector"] == data_selector
        # The wrapper key is documented for all of these, so a response without it is a changed
        # API shape and must fail loud rather than sync 0 rows.
        assert endpoint_config["data_selector_required"] is True

        if endpoint in UNPAGINATED_ENDPOINTS:
            assert isinstance(endpoint_config["paginator"], SinglePagePaginator)
            assert "page[size]" not in endpoint_config["params"]
        else:
            assert isinstance(endpoint_config["paginator"], JSONLinkPaginator)
            assert endpoint_config["params"]["page[size]"] == CURSOR_PAGE_SIZE

    def test_ticket_audits_paginates_on_its_own_cursor_field(self) -> None:
        # ticket_audits predates `links.next`; reading the wrong field would stop after one page.
        endpoint_config = _endpoint(get_resource("ticket_audits", should_use_incremental_field=False))
        paginator = endpoint_config["paginator"]

        assert isinstance(paginator, ZendeskAfterUrlPaginator)
        assert paginator.next_url_path == "after_url"

    def test_fanout_endpoint_is_not_built_as_a_top_level_resource(self) -> None:
        with pytest.raises(ValueError):
            get_declarative_resource(ZENDESK_ENDPOINTS["ticket_comments"], should_use_incremental_field=False)

    def test_every_fanout_parent_is_registered(self) -> None:
        for config in ZENDESK_ENDPOINTS.values():
            if config.fanout is not None:
                assert config.fanout.parent_name in FANOUT_PARENTS

    def test_fanout_supplies_the_parent_derived_primary_key_columns(self) -> None:
        # ticket_comments is keyed on (ticket_id, id); ticket_id only exists on the row because
        # the fan-out injects the parent's id, so dropping the rename would seed duplicate rows.
        config = ZENDESK_ENDPOINTS["ticket_comments"]
        assert config.fanout is not None
        assert set(config.primary_key) - {"id"} <= set(config.fanout.parent_field_renames.values())


class TestZendeskAfterUrlPaginator:
    def test_follows_after_url(self) -> None:
        p = ZendeskAfterUrlPaginator()
        p.update_state(
            _make_response({"audits": [{"id": 1}], "after_url": "https://x.zendesk.com/next"}), data=[{"id": 1}]
        )

        assert p.has_next_page is True

        req = Request(method="GET", url="https://x.zendesk.com/api/v2/ticket_audits")
        req.params = {"page[size]": 100}
        p.update_request(req)
        assert req.url == "https://x.zendesk.com/next"
        assert req.params == {}

    @pytest.mark.parametrize(
        "body,data",
        [
            pytest.param({"audits": [], "after_url": "https://x.zendesk.com/next"}, [], id="empty_page_with_cursor"),
            pytest.param({"audits": [{"id": 1}], "after_url": None}, [{"id": 1}], id="no_cursor"),
            pytest.param({"audits": [{"id": 1}]}, [{"id": 1}], id="cursor_absent"),
        ],
    )
    def test_stops_pagination(self, body: dict[str, Any], data: list[dict[str, Any]]) -> None:
        # The endpoint keeps handing back a cursor URL past the end of the stream, so an empty
        # page has to terminate too — otherwise the sync loops forever on the last page.
        p = ZendeskAfterUrlPaginator()

        p.update_state(_make_response(body), data=data)

        assert p.has_next_page is False


class TestZendeskDeclarativeIncremental:
    def test_activities_uses_the_server_side_since_filter(self) -> None:
        endpoint_config = _endpoint(get_resource("activities", should_use_incremental_field=True))
        incremental = endpoint_config["incremental"]

        assert incremental["start_param"] == "since"
        assert incremental["cursor_path"] == "created_at"
        # The plain list endpoints take ISO 8601, not the Unix epoch the incremental exports use.
        assert incremental["convert"] is to_zendesk_iso8601

    def test_activities_honors_the_users_chosen_cursor_field(self) -> None:
        endpoint_config = _endpoint(
            get_resource("activities", should_use_incremental_field=True, incremental_field_name="updated_at")
        )

        assert endpoint_config["incremental"]["cursor_path"] == "updated_at"

    @pytest.mark.parametrize(
        "endpoint,should_use_incremental_field,expects_incremental",
        [
            pytest.param("activities", True, True, id="activities_incremental"),
            pytest.param("activities", False, False, id="activities_full_refresh"),
            # No server-side time filter is documented for these, so they must stay full refresh
            # even when the schema is flagged incremental.
            pytest.param("satisfaction_ratings", True, False, id="satisfaction_ratings_stays_full_refresh"),
            pytest.param("audit_logs", True, False, id="audit_logs_stays_full_refresh"),
        ],
    )
    def test_write_disposition_follows_server_side_filter_support(
        self, endpoint: str, should_use_incremental_field: bool, expects_incremental: bool
    ) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=should_use_incremental_field)
        endpoint_config = _endpoint(resource)

        assert ("incremental" in endpoint_config) is expects_incremental
        assert resource["write_disposition"] == (
            {"disposition": "merge", "strategy": "upsert"} if expects_incremental else "replace"
        )


class TestToZendeskIso8601:
    @pytest.mark.parametrize(
        "value,expected",
        [
            pytest.param("1970-01-01T00:00:00Z", "1970-01-01T00:00:00Z", id="initial_value_passthrough"),
            pytest.param(datetime(2020, 6, 5, 21, 23, 6, tzinfo=UTC), "2020-06-05T21:23:06Z", id="aware_datetime"),
            pytest.param(datetime(2020, 6, 5, 21, 23, 6), "2020-06-05T21:23:06Z", id="naive_datetime_as_utc"),
            pytest.param(
                datetime(2020, 6, 5, 21, 23, 6, tzinfo=timezone(timedelta(hours=2))),
                "2020-06-05T19:23:06Z",
                id="offset_datetime_converted_to_utc",
            ),
        ],
    )
    def test_formats_for_the_since_filter(self, value: Any, expected: str) -> None:
        assert to_zendesk_iso8601(value) == expected


class _FakeResource:
    def __init__(self, name: str) -> None:
        self.name = name
        self.maps: list[Any] = []

    def add_map(self, fn: Any) -> "_FakeResource":
        self.maps.append(fn)
        return self


class TestZendeskTicketCommentsFanout:
    def _build(self) -> tuple[_FakeResource, list[Any]]:
        child = _FakeResource("ticket_comments")

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources",
            return_value=[_FakeResource("tickets_for_comments"), child],
        ) as mock_resources:
            zendesk_source(
                subdomain="nibbles",
                api_key="token",
                email_address="user@example.com",
                endpoint="ticket_comments",
                team_id=1,
                job_id="job-1",
                db_incremental_field_last_value=None,
            )

        return child, mock_resources.call_args[0]

    def test_parent_and_child_endpoints(self) -> None:
        _, args = self._build()
        parent, child = args[0]["resources"]

        assert parent["endpoint"]["path"] == "/api/v2/tickets"
        assert parent["endpoint"]["params"]["page[size]"] == CURSOR_PAGE_SIZE
        assert child["endpoint"]["path"] == "/api/v2/tickets/{ticket_id}/comments"
        # The ticket id is bound from the parent row into the child path.
        assert child["endpoint"]["params"]["ticket_id"] == {
            "type": "resolve",
            "resource": TICKET_COMMENTS_PARENT_NAME,
            "field": "id",
        }
        assert child["include_from_parent"] == ["id"]

    def test_comment_rows_carry_the_parent_ticket_id(self) -> None:
        # Without this rename a comment row has no ticket_id, so the (ticket_id, id) primary key
        # would never match and every sync would seed duplicates.
        child, _ = self._build()

        row = child.maps[0]({f"_{TICKET_COMMENTS_PARENT_NAME}_id": 42, "id": 7, "body": "hi"})

        assert row == {"ticket_id": 42, "id": 7, "body": "hi"}


class TestZendeskSchemas:
    def _schemas(self) -> dict[str, Any]:
        config = ZendeskSourceConfig(subdomain="nibbles", api_key="token", email_address="user@example.com")
        return {schema.name: schema for schema in ZendeskSource().get_schemas(config, team_id=1)}

    def test_every_declared_endpoint_is_offered_exactly_once(self) -> None:
        config = ZendeskSourceConfig(subdomain="nibbles", api_key="token", email_address="user@example.com")
        names = [schema.name for schema in ZendeskSource().get_schemas(config, team_id=1)]

        assert len(names) == len(set(names))
        assert set(ZENDESK_ENDPOINTS).issubset(names)
        # The endpoints that shipped first must keep being offered.
        assert {"tickets", "users", "organizations", "brands", "groups", "sla_policies"}.issubset(names)

    def test_only_endpoints_with_a_server_side_filter_advertise_incremental(self) -> None:
        schemas = self._schemas()
        incremental = {name for name in ZENDESK_ENDPOINTS if schemas[name].supports_incremental}

        assert incremental == {"activities"}
        assert schemas["activities"].incremental_fields[0]["field"] == "created_at"

    def test_canonical_descriptions_cover_every_new_table(self) -> None:
        descriptions = ZendeskSource().get_canonical_descriptions()

        for name in ZENDESK_ENDPOINTS:
            assert name in descriptions, f"{name} has no canonical description"
            assert descriptions[name]["description"]
            assert descriptions[name]["docs_url"].startswith("https://developer.zendesk.com/")


class TestZendeskSourceForPipeline:
    def _response(self, schema_name: str) -> Any:
        config = ZendeskSourceConfig(subdomain="nibbles", api_key="token", email_address="user@example.com")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source.zendesk_source",
            return_value=SimpleNamespace(name=schema_name, column_hints=None),
        ):
            return ZendeskSource().source_for_pipeline(config, _source_inputs(schema_name))

    @pytest.mark.parametrize(
        "schema_name,primary_keys,partition_key",
        [
            # The original endpoints keep the key and partition they have always synced with.
            pytest.param("tickets", ["id"], "created_at", id="tickets_unchanged"),
            pytest.param("ticket_metric_events", ["id"], "time", id="ticket_metric_events_unchanged"),
            # A tag row is just {name, count} — keying it on `id` would collapse the whole table.
            pytest.param("tags", ["name"], None, id="tags_keyed_on_name"),
            pytest.param("custom_objects", ["key"], "created_at", id="custom_objects_keyed_on_key"),
            pytest.param("ticket_comments", ["ticket_id", "id"], "created_at", id="ticket_comments_composite_key"),
            pytest.param("deleted_tickets", ["id"], "deleted_at", id="deleted_tickets_partitioned_on_deleted_at"),
            pytest.param("satisfaction_ratings", ["id"], "created_at", id="satisfaction_ratings"),
        ],
    )
    def test_primary_keys_and_partitioning(
        self, schema_name: str, primary_keys: list[str], partition_key: str | None
    ) -> None:
        response = self._response(schema_name)

        assert response.primary_keys == primary_keys
        assert response.partition_keys == ([partition_key] if partition_key else None)
        assert response.partition_mode == ("datetime" if partition_key else None)

    @pytest.mark.parametrize(
        "schema_name,sort_mode",
        [
            pytest.param("tickets", "asc", id="tickets_unchanged"),
            # The activity stream returns newest first, so the watermark must only be committed
            # once the sync completes.
            pytest.param("activities", "desc", id="activities_desc"),
            pytest.param("macros", "asc", id="macros_asc"),
        ],
    )
    def test_sort_mode(self, schema_name: str, sort_mode: str) -> None:
        assert self._response(schema_name).sort_mode == sort_mode
