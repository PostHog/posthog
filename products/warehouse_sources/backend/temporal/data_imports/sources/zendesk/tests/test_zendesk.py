import json
from collections.abc import Sequence
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (
    ParentTableRef,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
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
    ZendeskCursorIncrementalPaginator,
    ZendeskIncrementalEndpointPaginator,
    ZendeskResumeConfig,
    ZendeskSinceCursorPaginator,
    get_declarative_resource,
    get_resource,
    normalize_subdomain,
    to_zendesk_iso8601,
    to_zendesk_start_time,
    zendesk_source,
)


def _make_response(json_body: dict[str, Any] | None = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
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


class TestZendeskCursorIncrementalPaginator:
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


class TestZendeskIncrementalEndpointPaginator:
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


class TestZendeskSinceCursorPaginator:
    def test_drops_since_from_the_next_page_url(self) -> None:
        # Zendesk echoes `since` back into `links.next` in its own format, which it then
        # rejects on the next request (400). The cursor alone is enough to continue.
        p = ZendeskSinceCursorPaginator(next_url_path="links.next")
        next_url = (
            f"{BASE}/api/v2/activities.json?page%5Bafter%5D=abc123&page%5Bsize%5D=100&since=1970-01-01+00%3A00%3A00+UTC"
        )

        p.update_state(_make_response({"activities": [{"id": 1}], "links": {"next": next_url}}))

        req = Request(method="GET", url=f"{BASE}/api/v2/activities.json")
        req.params = {"page[size]": 100, "since": "1970-01-01T00:00:00Z"}
        p.update_request(req)

        assert "since" not in req.url
        assert "page%5Bafter%5D=abc123" in req.url
        assert req.params == {}

    def test_drops_since_from_a_restored_checkpoint(self) -> None:
        # A run that already failed on this URL checkpointed it with `since` still attached —
        # that's the exact failure this paginator exists to fix. A retry must not resume
        # straight back into the same URL, or it hits the same 400 forever.
        p = ZendeskSinceCursorPaginator(next_url_path="links.next")
        dirty_next_url = (
            f"{BASE}/api/v2/activities.json?page%5Bafter%5D=abc123&page%5Bsize%5D=100&since=1970-01-01+00%3A00%3A00+UTC"
        )

        p.set_resume_state({"next_url": dirty_next_url})

        req = Request(method="GET", url=f"{BASE}/api/v2/activities.json")
        req.params = {"page[size]": 100, "since": "1970-01-01T00:00:00Z"}
        p.init_request(req)

        assert "since" not in req.url
        assert "page%5Bafter%5D=abc123" in req.url


class TestZendeskDeclarativeIncremental:
    def test_activities_honors_the_users_chosen_cursor_field(self) -> None:
        endpoint_config = _endpoint(
            get_resource("activities", should_use_incremental_field=True, incremental_field_name="updated_at")
        )

        assert endpoint_config["incremental"]["cursor_path"] == "updated_at"


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


_UNSET = object()


class _FakeResource:
    def __init__(self, name: str) -> None:
        self.name = name
        self.maps: list[Any] = []
        self.filters: list[Any] = []

    def add_map(self, fn: Any) -> "_FakeResource":
        self.maps.append(fn)
        return self

    def add_filter(self, fn: Any) -> "_FakeResource":
        self.filters.append(fn)
        return self


class TestZendeskTicketCommentsFanout:
    def _build(self, should_use_incremental_field: bool = False) -> tuple[_FakeResource, list[Any]]:
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
                db_incremental_field_last_value="2026-01-01T00:00:00Z" if should_use_incremental_field else None,
                should_use_incremental_field=should_use_incremental_field,
            )

        return child, mock_resources.call_args[0]

    def test_comment_rows_carry_the_parent_ticket_id(self) -> None:
        # Without this rename a comment row has no ticket_id, so the (ticket_id, id) primary key
        # would never match and every sync would seed duplicates.
        child, _ = self._build()

        row = child.maps[0]({f"_{TICKET_COMMENTS_PARENT_NAME}_id": 42, "id": 7, "body": "hi"})

        assert row == {"ticket_id": 42, "id": 7, "body": "hi"}


class TestZendeskTicketCommentsWarehouseParent:
    def _build(
        self,
        watermark: Any,
        use_warehouse_parent: bool = True,
        snapshot_at: Any = _UNSET,
    ) -> tuple[Any, _FakeResource]:
        child = _FakeResource("ticket_comments")
        if snapshot_at is _UNSET:
            snapshot_at = datetime.now(UTC)
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources",
                return_value=[_FakeResource("tickets"), child],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.zendesk.parent_snapshot_covers_through",
                return_value=snapshot_at,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.resolve_parent_table_ref",
                return_value=ParentTableRef(uri="s3://bucket/team_1/tickets", version=3),
            ) as mock_resolve,
        ):
            zendesk_source(
                subdomain="nibbles",
                api_key="token",
                email_address="user@example.com",
                endpoint="ticket_comments",
                team_id=1,
                job_id="job-1",
                db_incremental_field_last_value=watermark,
                should_use_incremental_field=True,
                source_id="source-1",
                use_warehouse_parent=use_warehouse_parent,
            )
        return mock_resolve, child

    def _resolve(self, watermark: Any, use_warehouse_parent: bool = True, snapshot_at: Any = _UNSET) -> Any:
        return self._build(watermark, use_warehouse_parent, snapshot_at)[0]

    def test_takes_the_api_path_without_a_completed_parent_sync(self) -> None:
        assert self._resolve(datetime.now(UTC) - timedelta(hours=6), snapshot_at=None).call_count == 0

    def test_no_cap_when_the_parent_table_cannot_be_resolved(self) -> None:
        child = _FakeResource("ticket_comments")
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources",
                return_value=[_FakeResource("tickets"), child],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.zendesk.parent_snapshot_covers_through",
                return_value=datetime.now(UTC) - timedelta(hours=6),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent.try_resolve_parent_table",
                return_value=None,
            ),
        ):
            zendesk_source(
                subdomain="nibbles",
                api_key="token",
                email_address="user@example.com",
                endpoint="ticket_comments",
                team_id=1,
                job_id="job-1",
                db_incremental_field_last_value=datetime.now(UTC) - timedelta(hours=7),
                should_use_incremental_field=True,
                source_id="source-1",
                use_warehouse_parent=True,
            )

        assert child.filters == []


class TestZendeskRequiredParentSchemas:
    def test_source_for_pipeline_forwards_the_source_and_the_reuse_decision(self) -> None:
        config = ZendeskSourceConfig(subdomain="nibbles", api_key="token", email_address="user@example.com")
        inputs = _source_inputs("ticket_comments")
        inputs.fanout_warehouse_reuse = True

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk.source.zendesk_source",
            return_value=SimpleNamespace(name="ticket_comments", column_hints=None),
        ) as mock_source:
            ZendeskSource().source_for_pipeline(config, MagicMock(spec=ResumableSourceManager), inputs)

        assert mock_source.call_args.kwargs["source_id"] == "source-1"
        assert mock_source.call_args.kwargs["use_warehouse_parent"] is True


BASE = "https://nibbles.zendesk.com"

# Three pages per endpoint in the paginator's own response shape: two that continue and one that
# ends the stream, plus the resume config each continuing page must stage.
RESUME_CASES: dict[str, tuple[list[dict[str, Any]], list[ZendeskResumeConfig]]] = {
    "tickets": (
        [
            {"tickets": [{"id": 1}], "after_cursor": "c1", "end_of_stream": False},
            {"tickets": [{"id": 2}], "after_cursor": "c2", "end_of_stream": False},
            {"tickets": [{"id": 3}], "after_cursor": "c3", "end_of_stream": True},
        ],
        [ZendeskResumeConfig(cursor="c1"), ZendeskResumeConfig(cursor="c2")],
    ),
    "users": (
        [
            {"users": [{"id": 1}], "after_cursor": "u1", "end_of_stream": False},
            {"users": [{"id": 2}], "after_cursor": "u2", "end_of_stream": False},
            {"users": [{"id": 3}], "after_cursor": "u3", "end_of_stream": True},
        ],
        [ZendeskResumeConfig(cursor="u1"), ZendeskResumeConfig(cursor="u2")],
    ),
    "organizations": (
        [
            {"organizations": [{"id": 1}], "end_of_stream": False, "next_page": f"{BASE}/p2"},
            {"organizations": [{"id": 2}], "end_of_stream": False, "next_page": f"{BASE}/p3"},
            {"organizations": [{"id": 3}], "end_of_stream": True, "next_page": None},
        ],
        [ZendeskResumeConfig(next_url=f"{BASE}/p2"), ZendeskResumeConfig(next_url=f"{BASE}/p3")],
    ),
    "brands": (
        [
            {"brands": [{"id": 1}], "links": {"next": f"{BASE}/p2"}},
            {"brands": [{"id": 2}], "links": {"next": f"{BASE}/p3"}},
            {"brands": [{"id": 3}], "links": {"next": None}},
        ],
        [ZendeskResumeConfig(next_url=f"{BASE}/p2"), ZendeskResumeConfig(next_url=f"{BASE}/p3")],
    ),
    "ticket_audits": (
        [
            {"audits": [{"id": 1}], "after_url": f"{BASE}/p2"},
            {"audits": [{"id": 2}], "after_url": f"{BASE}/p3"},
            {"audits": [], "after_url": f"{BASE}/p4"},
        ],
        [ZendeskResumeConfig(next_url=f"{BASE}/p2"), ZendeskResumeConfig(next_url=f"{BASE}/p3")],
    ),
}


class TestZendeskResume:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        bodies: Sequence[dict[str, Any] | Response],
        should_use_incremental_field: bool,
    ) -> list[tuple[str, dict[str, Any]]]:
        sent: list[tuple[str, dict[str, Any]]] = []
        responses = iter(bodies)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent.append((request.url, dict(request.params or {})))
            body = next(responses)
            return body if isinstance(body, Response) else _make_response(body)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as mock_session_factory:
            session = mock_session_factory.return_value
            session.headers = {}
            session.prepare_request.side_effect = lambda req: req
            session.send.side_effect = fake_send

            resource = zendesk_source(
                subdomain="nibbles",
                api_key="token",
                email_address="user@example.com",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                db_incremental_field_last_value=None,
                should_use_incremental_field=should_use_incremental_field,
                resumable_source_manager=manager,
            )
            list(resource)
        return sent

    @pytest.mark.parametrize("should_use_incremental_field", [False, True], ids=["full_refresh", "incremental"])
    @pytest.mark.parametrize("endpoint", sorted(RESUME_CASES))
    def test_fresh_run_stages_the_next_page_after_each_page(
        self, endpoint: str, should_use_incremental_field: bool
    ) -> None:
        bodies, expected = RESUME_CASES[endpoint]
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        sent = self._drive(endpoint, manager, bodies, should_use_incremental_field)

        assert len(sent) == 3
        assert [call.args[0] for call in manager.save_state.call_args_list] == expected
        manager.load_state.assert_not_called()

    @pytest.mark.parametrize("should_use_incremental_field", [False, True], ids=["full_refresh", "incremental"])
    @pytest.mark.parametrize("endpoint", sorted(RESUME_CASES))
    def test_resumed_run_starts_at_the_saved_page(self, endpoint: str, should_use_incremental_field: bool) -> None:
        bodies, expected = RESUME_CASES[endpoint]
        saved = expected[-1]
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = saved

        sent = self._drive(endpoint, manager, bodies[-1:], should_use_incremental_field)

        assert len(sent) == 1
        url, params = sent[0]
        if saved.cursor is not None:
            assert params["cursor"] == saved.cursor
            # The seed `start_time` would restart the export from the watermark, not the cursor.
            assert "start_time" not in params
        else:
            assert url == saved.next_url
            # The saved URL carries its own query string; re-sending the seed params duplicates them.
            assert params == {}
        manager.save_state.assert_not_called()

    def test_expired_cursor_is_cleared_before_retry(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ZendeskResumeConfig(cursor="expired")

        with pytest.raises(RuntimeError, match="rejected the saved pagination cursor"):
            self._drive(
                "tickets",
                manager,
                [_make_response({"error": "Invalid cursor: cursor has expired"}, status_code=400)],
                False,
            )

        manager.clear_state.assert_called_once_with()
