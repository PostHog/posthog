import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Optional, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.knock import (
    NO_OBJECT_COLLECTIONS_ERROR,
    KnockResumeConfig,
    get_resource,
    knock_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import ENDPOINTS_CONFIG


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(endpoint: str, rows: list[dict[str, Any]], after: str | None) -> Response:
    selector = ENDPOINTS_CONFIG[endpoint].data_selector
    return _make_http_response({selector: rows, "page_info": {"after": after, "before": None, "page_size": 50}})


class TestGetResource:
    @parameterized.expand(
        [
            ("messages", "inserted_at[gte]"),
            ("workflow_recipient_runs", "starting_at"),
        ]
    )
    def test_incremental_uses_endpoint_specific_server_filter(self, endpoint: str, expected_param: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert params[expected_param]["type"] == "incremental"
        assert params[expected_param]["cursor_path"] == "inserted_at"
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}

    @parameterized.expand([("messages",), ("users",), ("tenants",), ("workflow_recipient_runs",)])
    def test_full_refresh_sends_no_timestamp_filter(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=False)
        params = cast(dict[str, Any], cast(dict[str, Any], resource["endpoint"])["params"])
        assert set(params) == {"page_size"}
        assert resource["write_disposition"] == "replace"


class TestKnockSourceTransport:
    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Optional[Any] = None,
        object_collections: Optional[str] = None,
        sent_urls: Optional[list[str]] = None,
    ) -> tuple[SourceResponse, list[dict[str, Any]], list[dict[str, Any]]]:
        # Capture shallow copies of request.params at send-time: the Request object is
        # mutated in place by the paginator between pages.
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            if sent_urls is not None:
                sent_urls.append(request.url)
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            source_response = knock_source(
                api_key="sk_test",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                object_collections=object_collections,
            )
            rows = [row for chunk in cast(Iterable[Any], source_response.items()) for row in chunk]
            return source_response, sent_params, rows

    @parameterized.expand(
        [
            # Messages and workflow recipient runs wrap rows in `items`; users and
            # tenants wrap them in `entries` — a swapped selector syncs 0 rows.
            ("messages",),
            ("users",),
        ]
    )
    def test_rows_extracted_from_endpoint_envelope(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page(endpoint, [{"id": "a"}, {"id": "b"}], after=None)]
        _, _, rows = self._drive(endpoint, manager, responses)

        assert [row["id"] for row in rows] == ["a", "b"]

    def test_fresh_run_pages_on_after_cursor_and_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _page("messages", [{"id": "m1"}], after="cursor-1"),
            _page("messages", [{"id": "m2"}], after="cursor-2"),
            _page("messages", [{"id": "m3"}], after=None),
        ]
        _, sent_params, rows = self._drive("messages", manager, responses)

        assert [p.get("after") for p in sent_params] == [None, "cursor-1", "cursor-2"]
        # page_size rides along on every request.
        assert all(p.get("page_size") == 50 for p in sent_params)
        assert [row["id"] for row in rows] == ["m1", "m2", "m3"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [KnockResumeConfig(after="cursor-1"), KnockResumeConfig(after="cursor-2")]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = KnockResumeConfig(after="cursor-resumed")

        responses = [_page("messages", [{"id": "m9"}], after=None)]
        _, sent_params, _ = self._drive("messages", manager, responses)

        assert [p.get("after") for p in sent_params] == ["cursor-resumed"]

    def test_incremental_run_sends_watermark_as_iso8601(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_page("messages", [{"id": "m1", "inserted_at": "2026-06-01T00:00:00Z"}], after=None)]
        _, sent_params, _ = self._drive(
            "messages",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, 12, 30),
        )

        assert sent_params[0]["inserted_at[gte]"] == "2026-05-01T12:30:00"

    @parameterized.expand(
        [
            ("messages", ["inserted_at"], ["id"]),
            ("workflow_recipient_runs", ["inserted_at"], ["id"]),
            ("users", None, ["id"]),
            ("tenants", None, ["id"]),
            # Child ids are only guaranteed unique per parent, so the parent id joins the key.
            ("message_events", ["inserted_at"], ["message_id", "id"]),
            ("message_delivery_logs", ["inserted_at"], ["message_id", "id"]),
            ("objects", None, ["collection", "id"]),
        ]
    )
    def test_source_response_partitioning_and_sort_mode(
        self, endpoint: str, partition_keys: list[str] | None, primary_keys: list[str]
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        fanout = ENDPOINTS_CONFIG[endpoint].fanout
        first_page = _page(fanout.parent_name if fanout else endpoint, [], after=None)
        source_response, _, _ = self._drive(endpoint, manager, [first_page], object_collections="accounts")

        assert source_response.primary_keys == primary_keys
        # Knock lists return newest-first, so the pipeline must not checkpoint the
        # watermark per batch.
        assert source_response.sort_mode == "desc"
        assert source_response.partition_keys == partition_keys
        assert source_response.partition_mode == ("datetime" if partition_keys else None)

    @parameterized.expand(
        [
            ("message_events", "events"),
            ("message_delivery_logs", "delivery_logs"),
        ]
    )
    def test_message_fanout_windows_parent_walk_and_tags_child_rows(self, endpoint: str, child_path: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        sent_urls: list[str] = []

        responses = [
            _page("messages", [{"id": "m1", "inserted_at": "2026-06-01T00:00:00Z"}], after="cursor-1"),
            _make_http_response({"items": [{"id": "e1", "inserted_at": "2026-06-01T00:00:05Z"}], "page_info": {}}),
            _page("messages", [{"id": "m2", "inserted_at": "2026-06-02T00:00:00Z"}], after=None),
            _make_http_response({"items": [{"id": "e1", "inserted_at": "2026-06-02T00:00:05Z"}], "page_info": {}}),
        ]
        _, sent_params, rows = self._drive(
            endpoint,
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, 12, 30),
            sent_urls=sent_urls,
        )

        assert [url.rsplit("/v1/", 1)[1] for url in sent_urls] == [
            "messages",
            f"messages/m1/{child_path}",
            "messages",
            f"messages/m2/{child_path}",
        ]
        # The child endpoints take no timestamp filter, so the watermark bounds the parent walk.
        assert sent_params[0]["inserted_at[gte]"] == "2026-05-01T12:30:00"
        assert sent_params[2]["after"] == "cursor-1"
        assert all("inserted_at[gte]" not in params for params in sent_params[1::2])
        assert [(r["message_id"], r["id"], r["message_inserted_at"]) for r in rows] == [
            ("m1", "e1", "2026-06-01T00:00:00Z"),
            ("m2", "e1", "2026-06-02T00:00:00Z"),
        ]

    def test_message_fanout_full_refresh_walks_every_message(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _page("messages", [{"id": "m1", "inserted_at": "2026-06-01T00:00:00Z"}], after=None),
            _make_http_response({"items": [{"id": "e1"}], "page_info": {}}),
        ]
        _, sent_params, _ = self._drive("message_events", manager, responses)

        assert set(sent_params[0]) == {"page_size"}

    def test_schedules_fan_out_over_percent_encoded_user_ids(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        sent_urls: list[str] = []

        responses = [
            _page("users", [{"id": "team/jane"}], after=None),
            _make_http_response({"entries": [{"id": "s1"}], "page_info": {}}),
        ]
        _, _, rows = self._drive("schedules", manager, responses, sent_urls=sent_urls)

        assert sent_urls[1].endswith("/v1/users/team%2Fjane/schedules")
        assert [row["id"] for row in rows] == ["s1"]

    def test_objects_walk_each_configured_collection(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        sent_urls: list[str] = []

        responses = [
            _page("objects", [{"id": "a1", "collection": "accounts"}], after="cursor-1"),
            _page("objects", [{"id": "a2", "collection": "accounts"}], after=None),
            _page("objects", [{"id": "p1", "collection": "projects"}], after=None),
        ]
        _, sent_params, rows = self._drive(
            "objects", manager, responses, object_collections=" accounts, projects,accounts ", sent_urls=sent_urls
        )

        assert [url.rsplit("/v1/", 1)[1] for url in sent_urls] == ["objects/accounts"] * 2 + ["objects/projects"]
        assert [p.get("after") for p in sent_params] == [None, "cursor-1", None]
        assert [row["id"] for row in rows] == ["a1", "a2", "p1"]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            KnockResumeConfig(collection="accounts"),
            KnockResumeConfig(after="cursor-1", collection="accounts"),
            KnockResumeConfig(collection="projects"),
        ]

    def test_objects_resume_skips_finished_collections(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = KnockResumeConfig(after="cursor-7", collection="projects")
        sent_urls: list[str] = []

        responses = [_page("objects", [{"id": "p8", "collection": "projects"}], after=None)]
        _, sent_params, _ = self._drive(
            "objects", manager, responses, object_collections="accounts,projects", sent_urls=sent_urls
        )

        assert [url.rsplit("/v1/", 1)[1] for url in sent_urls] == ["objects/projects"]
        assert sent_params[0]["after"] == "cursor-7"

    @parameterized.expand([(None,), ("",), (" , ",)])
    def test_objects_without_collections_fails_with_actionable_error(self, object_collections: str | None) -> None:
        manager = MagicMock(spec=ResumableSourceManager)

        with pytest.raises(ValueError, match=NO_OBJECT_COLLECTIONS_ERROR):
            knock_source(
                api_key="sk_test",
                endpoint="objects",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=None,
                object_collections=object_collections,
            )


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("valid", 200, {}, (True, None)),
            (
                "invalid_key",
                401,
                {"code": "api_key_invalid", "message": "The API key you supplied is invalid"},
                (False, "The API key you supplied is invalid"),
            ),
            ("auth_error_without_body", 401, {}, (False, "Invalid Knock API key")),
            ("server_error", 500, {}, (False, "Knock API returned an unexpected response (HTTP 500)")),
        ]
    )
    def test_status_mapping(
        self, _name: str, status_code: int, body: dict[str, Any], expected: tuple[bool, str | None]
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.knock.knock.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = _make_http_response(body, status_code)
            assert validate_credentials("sk_test") == expected
