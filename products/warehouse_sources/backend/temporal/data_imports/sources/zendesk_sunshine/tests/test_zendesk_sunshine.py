from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.settings import (
    DEFAULT_QUERY_WINDOW_START,
    ZENDESK_SUNSHINE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.zendesk_sunshine import (
    SunshineLinksPaginator,
    SunshineObjectQueryPaginator,
    ZendeskSunshineResumeConfig,
    _fanout_resources,
    _query_resource,
    get_base_url,
    list_object_type_keys,
    normalize_subdomain,
    to_query_datetime,
    validate_credentials,
    zendesk_sunshine_source,
)

BASE_URL = "https://nibbles.zendesk.com/api/sunshine/"
MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sunshine.zendesk_sunshine"


class _FakeResumeManager:
    def __init__(self, state: Optional[dict[str, Any]] = None) -> None:
        self._state = state
        self.saved: list[dict[str, Any]] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[ZendeskSunshineResumeConfig]:
        return ZendeskSunshineResumeConfig(state=self._state) if self._state is not None else None

    def save_state(self, data: ZendeskSunshineResumeConfig) -> None:
        self.saved.append(data.state)


class _FakeResource:
    def __init__(self, name: str, pages: Optional[list[list[dict[str, Any]]]] = None) -> None:
        self.name = name
        self.maps: list[Any] = []
        self._pages = pages or []

    def add_map(self, fn: Any) -> "_FakeResource":
        self.maps.append(fn)
        return self

    def __iter__(self):
        return iter(self._pages)


def _response(body: dict[str, Any]) -> mock.Mock:
    response = mock.Mock()
    response.json.return_value = body
    return response


def _collect_pages(response: SourceResponse) -> list[list[dict[str, Any]]]:
    items = response.items()
    assert isinstance(items, Iterable)
    return cast(list[list[dict[str, Any]]], list(items))


class TestZendeskSunshineTransport:
    @parameterized.expand(
        [
            ("bare", "nibbles", "nibbles"),
            ("full_host", "nibbles.zendesk.com", "nibbles"),
            ("url", "https://nibbles.zendesk.com/", "nibbles"),
            ("url_with_path", "https://nibbles.zendesk.com/agent", "nibbles"),
            ("mixed_case_host", "Nibbles.Zendesk.Com", "Nibbles"),
            ("whitespace", "  nibbles ", "nibbles"),
        ]
    )
    def test_normalize_subdomain(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_subdomain(raw) == expected

    def test_get_base_url(self) -> None:
        assert get_base_url("nibbles") == BASE_URL
        assert get_base_url("https://nibbles.zendesk.com") == BASE_URL

    @parameterized.expand(
        [
            ("none", None, None),
            ("naive_datetime_assumed_utc", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02 03:04:05.000"),
            (
                "aware_datetime_converted",
                datetime(2026, 1, 2, 4, 4, 5, 500000, tzinfo=timezone(timedelta(hours=1))),
                "2026-01-02 03:04:05.500",
            ),
            ("iso_string", "2026-01-02T03:04:05.123Z", "2026-01-02 03:04:05.123"),
            ("microseconds_truncated", datetime(2026, 1, 2, 3, 4, 5, 123999, tzinfo=UTC), "2026-01-02 03:04:05.123"),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_to_query_datetime(self, _name: str, value: Any, expected: str | None) -> None:
        assert to_query_datetime(value) == expected

    def test_links_paginator_absolutizes_relative_next(self) -> None:
        paginator = SunshineLinksPaginator(BASE_URL)
        paginator.update_state(
            _response({"data": [], "links": {"next": "/api/sunshine/objects/types?page[after]=abc"}})
        )

        assert paginator.has_next_page is True
        request = Request(method="GET", url=f"{BASE_URL}objects/types", params={"per_page": 100})
        paginator.update_request(request)
        assert request.url == "https://nibbles.zendesk.com/api/sunshine/objects/types?page[after]=abc"
        # The next link is self-contained; params must not be re-appended.
        assert request.params == {}

    def test_links_paginator_keeps_absolute_next(self) -> None:
        paginator = SunshineLinksPaginator(BASE_URL)
        next_url = f"{BASE_URL}objects/types?page[after]=abc"
        paginator.update_state(_response({"data": [], "links": {"next": next_url}}))

        request = Request(method="GET", url=f"{BASE_URL}objects/types")
        paginator.update_request(request)
        assert request.url == next_url

    def test_links_paginator_stops_on_null_next(self) -> None:
        paginator = SunshineLinksPaginator(BASE_URL)
        paginator.update_state(_response({"data": [], "links": {"next": None}}))
        assert paginator.has_next_page is False

    def test_links_paginator_resume_state_round_trip(self) -> None:
        paginator = SunshineLinksPaginator(BASE_URL)
        paginator.update_state(
            _response({"data": [], "links": {"next": "/api/sunshine/objects/types?page[after]=abc"}})
        )
        state = paginator.get_resume_state()
        assert state is not None

        resumed = SunshineLinksPaginator(BASE_URL)
        resumed.set_resume_state(state)
        request = Request(method="GET", url=f"{BASE_URL}objects/types", params={"per_page": 100})
        resumed.init_request(request)
        assert request.url == "https://nibbles.zendesk.com/api/sunshine/objects/types?page[after]=abc"

    def _query_request(self, window_start: str = DEFAULT_QUERY_WINDOW_START) -> Request:
        resource = _query_resource("product", window_start, BASE_URL)
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)
        return Request(
            method="POST",
            url=f"{BASE_URL}objects/query",
            params=dict(endpoint["params"] or {}),
            json=dict(endpoint["json"] or {}),
        )

    def test_query_resource_shape(self) -> None:
        resource = _query_resource("product", "2026-01-01 00:00:00.000", BASE_URL)
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)
        assert endpoint["method"] == "POST"
        assert endpoint["json"] == {
            "query": {"_type": {"$eq": "product"}},
            "sort_by": "_updated_at asc",
            "_updated_at": {"start": "2026-01-01 00:00:00.000"},
        }
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    def test_query_paginator_follows_next_and_keeps_window(self) -> None:
        paginator = SunshineObjectQueryPaginator(BASE_URL, DEFAULT_QUERY_WINDOW_START, max_pages_per_window=5)
        request = self._query_request()
        paginator.init_request(request)
        assert request.json["_updated_at"] == {"start": DEFAULT_QUERY_WINDOW_START}

        paginator.update_state(
            _response(
                {
                    "data": [{"id": "1", "updated_at": "2026-01-01T00:00:00.000Z"}],
                    "links": {"next": "/api/sunshine/objects/query?per_page=1000&cursor=abc"},
                }
            ),
            data=[{"id": "1", "updated_at": "2026-01-01T00:00:00.000Z"}],
        )
        paginator.update_request(request)

        assert request.url == "https://nibbles.zendesk.com/api/sunshine/objects/query?per_page=1000&cursor=abc"
        assert request.json["_updated_at"] == {"start": DEFAULT_QUERY_WINDOW_START}

    def test_query_paginator_rewindows_before_page_cap(self) -> None:
        paginator = SunshineObjectQueryPaginator(BASE_URL, DEFAULT_QUERY_WINDOW_START, max_pages_per_window=2)
        request = self._query_request()
        paginator.init_request(request)

        page1 = [{"id": "1", "updated_at": "2026-01-01T00:00:00.000Z"}]
        paginator.update_state(_response({"data": page1, "links": {"next": "/q?cursor=a"}}), data=page1)
        paginator.update_request(request)

        page2 = [{"id": "2", "updated_at": "2026-02-03T04:05:06.789Z"}]
        paginator.update_state(_response({"data": page2, "links": {"next": "/q?cursor=b"}}), data=page2)
        paginator.update_request(request)

        # Window re-anchored on the newest updated_at; pagination restarts at the query URL.
        assert request.url == f"{BASE_URL}objects/query?per_page=1000"
        assert request.json["_updated_at"] == {"start": "2026-02-03 04:05:06.789"}
        assert paginator.has_next_page is True

    def test_query_paginator_raises_when_window_cannot_advance(self) -> None:
        window_start = "2026-01-01 00:00:00.000"
        paginator = SunshineObjectQueryPaginator(BASE_URL, window_start, max_pages_per_window=1)
        page = [{"id": "1", "updated_at": "2026-01-01T00:00:00.000Z"}]

        with pytest.raises(ValueError, match="cannot advance"):
            paginator.update_state(_response({"data": page, "links": {"next": "/q?cursor=a"}}), data=page)

    def test_query_paginator_raises_when_no_timestamp_to_rewindow_from(self) -> None:
        paginator = SunshineObjectQueryPaginator(BASE_URL, DEFAULT_QUERY_WINDOW_START, max_pages_per_window=1)
        page = [{"id": "1"}]

        with pytest.raises(ValueError, match="re-window"):
            paginator.update_state(_response({"data": page, "links": {"next": "/q?cursor=a"}}), data=page)

    def test_query_paginator_stops_naturally_at_page_cap_without_next(self) -> None:
        paginator = SunshineObjectQueryPaginator(BASE_URL, DEFAULT_QUERY_WINDOW_START, max_pages_per_window=1)
        page = [{"id": "1", "updated_at": "2026-01-01T00:00:00.000Z"}]
        paginator.update_state(_response({"data": page, "links": {"next": None}}), data=page)
        assert paginator.has_next_page is False

    def test_query_paginator_resume_state_round_trip(self) -> None:
        paginator = SunshineObjectQueryPaginator(BASE_URL, "2026-01-01 00:00:00.000", max_pages_per_window=10)
        page = [{"id": "1", "updated_at": "2026-01-05T00:00:00.000Z"}]
        paginator.update_state(_response({"data": page, "links": {"next": "/q?cursor=a"}}), data=page)

        state = paginator.get_resume_state()
        assert state is not None
        assert state["window_start"] == "2026-01-01 00:00:00.000"
        assert state["pages_in_window"] == 1

        resumed = SunshineObjectQueryPaginator(BASE_URL, DEFAULT_QUERY_WINDOW_START, max_pages_per_window=10)
        resumed.set_resume_state(state)
        request = self._query_request()
        resumed.init_request(request)
        assert request.url == "https://nibbles.zendesk.com/q?cursor=a"
        # The resumed request keeps the saved window, not the constructor default.
        assert request.json["_updated_at"] == {"start": "2026-01-01 00:00:00.000"}

    def test_fanout_resources_resolve_parent_key_into_path(self) -> None:
        endpoint_config = ZENDESK_SUNSHINE_ENDPOINTS["relationship_records"]
        parent_config = ZENDESK_SUNSHINE_ENDPOINTS["relationship_types"]
        parent, child = _fanout_resources(endpoint_config, parent_config, BASE_URL)
        assert isinstance(parent, dict) and isinstance(child, dict)

        assert parent["name"] == "relationship_types"
        child_endpoint = child["endpoint"]
        assert isinstance(child_endpoint, dict)
        assert child_endpoint["path"] == "relationships/records?type={relationship_type}"
        child_params = child_endpoint["params"]
        assert child_params is not None
        assert child_params["relationship_type"] == {
            "type": "resolve",
            "resource": "relationship_types",
            "field": "key",
        }
        assert child_params["per_page"] == 1000

    def test_fanout_resources_policies_are_single_page(self) -> None:
        endpoint_config = ZENDESK_SUNSHINE_ENDPOINTS["object_type_policies"]
        parent_config = ZENDESK_SUNSHINE_ENDPOINTS["object_types"]
        _parent, child = _fanout_resources(endpoint_config, parent_config, BASE_URL)
        assert isinstance(child, dict)

        child_endpoint = child["endpoint"]
        assert isinstance(child_endpoint, dict)
        assert "per_page" not in (child_endpoint["params"] or {})
        assert child["include_from_parent"] == ["key"]

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("unauthorized", 401, False, "rejected the credentials"),
            ("forbidden", 403, False, "not available"),
            ("not_found", 404, False, "not available"),
            ("teapot", 418, False, "unexpected response"),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, expected_valid: bool, message_fragment: str | None
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.Mock(status_code=status_code)

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("nibbles", "token", "agent@example.com")

        assert is_valid is expected_valid
        if message_fragment is None:
            assert message is None
        else:
            assert message is not None and message_fragment in message
        assert session.get.call_args.kwargs["auth"] == ("agent@example.com/token", "token")

    def test_list_object_type_keys_follows_pagination(self) -> None:
        session = mock.MagicMock()
        page1 = mock.Mock(status_code=200)
        page1.json.return_value = {
            "data": [{"key": "product"}, {"key": "order"}],
            "links": {"next": "/api/sunshine/objects/types?page[after]=abc"},
        }
        page2 = mock.Mock(status_code=200)
        page2.json.return_value = {"data": [{"key": "shipment"}], "links": {"next": None}}
        session.get.side_effect = [page1, page2]

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            keys = list_object_type_keys("nibbles", "token", "agent@example.com")

        assert keys == ["product", "order", "shipment"]
        second_call = session.get.call_args_list[1]
        assert second_call.args[0] == "https://nibbles.zendesk.com/api/sunshine/objects/types?page[after]=abc"
        assert second_call.kwargs["params"] is None


class TestZendeskSunshineSourceResponses:
    def _fake_rest_api_resources(self, config: dict[str, Any], *args: Any, **kwargs: Any) -> list[_FakeResource]:
        return [_FakeResource(resource["name"]) for resource in config["resources"]]

    @parameterized.expand(
        [
            ("object_types", ["key"], ["created_at"]),
            ("object_records", ["id"], ["created_at"]),
            ("object_type_policies", ["object_type"], None),
            ("relationship_types", ["key"], ["created_at"]),
            ("relationship_records", ["id"], ["created_at"]),
            ("limits", ["key"], None),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, expected_primary_keys: list[str], expected_partition_keys: list[str] | None
    ) -> None:
        with (
            mock.patch(
                f"{MODULE}.rest_api_resource",
                side_effect=lambda config, *a, **k: _FakeResource(config["resources"][0]["name"]),
            ),
            mock.patch(f"{MODULE}.rest_api_resources", side_effect=self._fake_rest_api_resources),
        ):
            response = zendesk_sunshine_source(
                subdomain="nibbles",
                api_key="token",
                email_address="agent@example.com",
                endpoint=endpoint,
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_FakeResumeManager(),  # type: ignore[arg-type]
            )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.sort_mode == "asc"
        assert response.partition_keys == expected_partition_keys
        if expected_partition_keys:
            assert response.partition_mode == "datetime"

    def test_policies_rows_carry_object_type_from_parent(self) -> None:
        with mock.patch(f"{MODULE}.rest_api_resources", side_effect=self._fake_rest_api_resources):
            response = zendesk_sunshine_source(
                subdomain="nibbles",
                api_key="token",
                email_address="agent@example.com",
                endpoint="object_type_policies",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=_FakeResumeManager(),  # type: ignore[arg-type]
            )

        resource = response.items()
        assert isinstance(resource, _FakeResource)
        assert len(resource.maps) == 1
        row = resource.maps[0]({"_object_types_key": "product", "rbac": {"admin": {"read": True}}})
        assert row == {"object_type": "product", "rbac": {"admin": {"read": True}}}


class TestZendeskSunshineIncrementalObjectRecords:
    def _run(
        self,
        manager: _FakeResumeManager,
        db_incremental_field_last_value: Any = None,
        type_keys: Optional[list[str]] = None,
        pages_by_type: Optional[dict[str, list[list[dict[str, Any]]]]] = None,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        pages_by_type = pages_by_type or {}

        def fake_rest_api_resource(config: dict[str, Any], *args: Any, **kwargs: Any) -> _FakeResource:
            type_key = config["resources"][0]["endpoint"]["json"]["query"]["_type"]["$eq"]
            return _FakeResource("object_records", pages_by_type.get(type_key, [[{"id": f"{type_key}-row"}]]))

        with (
            mock.patch(f"{MODULE}.list_object_type_keys", return_value=type_keys or ["alpha", "beta"]),
            mock.patch(f"{MODULE}.rest_api_resource", side_effect=fake_rest_api_resource) as mock_resource,
        ):
            response = zendesk_sunshine_source(
                subdomain="nibbles",
                api_key="token",
                email_address="agent@example.com",
                endpoint="object_records",
                team_id=1,
                job_id="job-1",
                resumable_source_manager=manager,  # type: ignore[arg-type]
                should_use_incremental_field=True,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
            pages = _collect_pages(response)
        return pages, mock_resource

    def test_fresh_run_walks_every_type_and_checkpoints(self) -> None:
        manager = _FakeResumeManager()
        pages, mock_resource = self._run(manager)

        assert pages == [[{"id": "alpha-row"}], [{"id": "beta-row"}]]
        assert mock_resource.call_count == 2
        for call, type_key in zip(mock_resource.call_args_list, ["alpha", "beta"]):
            body = call.args[0]["resources"][0]["endpoint"]["json"]
            assert body["query"] == {"_type": {"$eq": type_key}}
            assert body["_updated_at"] == {"start": DEFAULT_QUERY_WINDOW_START}

        # A checkpoint lands after each completed type; the final one marks both done.
        assert manager.saved[-1]["completed"] == ["alpha", "beta"]
        assert manager.saved[-1]["current"] is None
        assert manager.saved[-1]["child_state"] is None

    def test_watermark_seeds_query_window(self) -> None:
        manager = _FakeResumeManager()
        _pages, mock_resource = self._run(
            manager, db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        )
        body = mock_resource.call_args_list[0].args[0]["resources"][0]["endpoint"]["json"]
        assert body["_updated_at"] == {"start": "2026-01-02 03:04:05.000"}

    def test_resume_skips_completed_types_and_seeds_child_state(self) -> None:
        child_state = {"next_url": f"{BASE_URL}q?cursor=x", "window_start": "2025-06-01 00:00:00.000"}
        manager = _FakeResumeManager(
            state={
                "window_start": "2025-06-01 00:00:00.000",
                "completed": ["alpha"],
                "current": "beta",
                "child_state": child_state,
            }
        )
        pages, mock_resource = self._run(
            manager,
            # A newer watermark must NOT reshape the window mid-job: the saved window wins, so
            # types that had not started when the previous attempt died keep their history.
            db_incremental_field_last_value=datetime(2026, 6, 1, tzinfo=UTC),
        )

        assert pages == [[{"id": "beta-row"}]]
        mock_resource.assert_called_once()
        call = mock_resource.call_args
        body = call.args[0]["resources"][0]["endpoint"]["json"]
        assert body["query"] == {"_type": {"$eq": "beta"}}
        assert body["_updated_at"] == {"start": "2025-06-01 00:00:00.000"}
        assert call.kwargs["initial_paginator_state"] == child_state


class TestZendeskSunshineFrameworkIntegration:
    """Drive the real rest_source framework against a mocked HTTP layer.

    Guards the declarative wiring the mocked tests can't: that the resolve placeholder
    binds into the path (including the query-string form), that fan-out children inherit
    parent fields, and that the incremental query POSTs the expected body.
    """

    def _source_response(self, endpoint: str, manager: _FakeResumeManager, **kwargs: Any) -> Any:
        return zendesk_sunshine_source(
            subdomain="nibbles",
            api_key="token",
            email_address="agent@example.com",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=manager,  # type: ignore[arg-type]
            **kwargs,
        )

    def test_relationship_records_fanout_binds_type_into_query_string(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{BASE_URL}relationships/types",
            json={"data": [{"key": "order_rel"}], "links": {"next": None}},
        )
        requests_mock.get(
            f"{BASE_URL}relationships/records",
            json={"data": [{"id": "r1", "relationship_type": "order_rel"}], "links": {"next": None}},
        )

        response = self._source_response("relationship_records", _FakeResumeManager())
        rows = [row for page in _collect_pages(response) for row in page]

        assert rows == [{"id": "r1", "relationship_type": "order_rel"}]
        records_request = next(r for r in requests_mock.request_history if "relationships/records" in r.path)
        assert records_request.qs["type"] == ["order_rel"]
        assert records_request.qs["per_page"] == ["1000"]

    def test_policies_fanout_resolves_path_and_injects_parent_key(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{BASE_URL}objects/types",
            json={"data": [{"key": "product"}], "links": {"next": None}},
        )
        requests_mock.get(
            f"{BASE_URL}objects/types/product/permissions",
            json={"data": {"rbac": {"admin": {"read": True}}}},
        )

        response = self._source_response("object_type_policies", _FakeResumeManager())
        rows = [row for page in _collect_pages(response) for row in page]

        assert rows == [{"rbac": {"admin": {"read": True}}, "object_type": "product"}]

    def test_incremental_object_records_posts_windowed_query(self, requests_mock: Any) -> None:
        requests_mock.get(
            f"{BASE_URL}objects/types",
            json={"data": [{"key": "product"}], "links": {"next": None}},
        )
        requests_mock.post(
            f"{BASE_URL}objects/query",
            json={"data": [{"id": "1", "updated_at": "2026-01-05T00:00:00.000Z"}], "links": {"next": None}},
        )

        manager = _FakeResumeManager()
        response = self._source_response(
            "object_records",
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
        rows = [row for page in _collect_pages(response) for row in page]

        assert rows == [{"id": "1", "updated_at": "2026-01-05T00:00:00.000Z"}]
        query_request = next(r for r in requests_mock.request_history if r.method == "POST")
        assert query_request.json() == {
            "query": {"_type": {"$eq": "product"}},
            "sort_by": "_updated_at asc",
            "_updated_at": {"start": "2026-01-02 03:04:05.000"},
        }
        assert query_request.qs["per_page"] == ["1000"]
        # The completed type is checkpointed so a retry skips it.
        assert manager.saved[-1]["completed"] == ["product"]
