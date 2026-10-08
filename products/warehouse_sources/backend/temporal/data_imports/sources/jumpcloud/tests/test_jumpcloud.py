import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud import jumpcloud
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.jumpcloud import (
    EVENTS_PAGE_SIZE,
    REST_PAGE_SIZE,
    JumpcloudResumeConfig,
    JumpcloudRetryableError,
    _parse_search_after,
    get_rows,
    jumpcloud_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.jumpcloud.settings import (
    ENDPOINTS,
    JUMPCLOUD_ENDPOINTS,
)


class _FakeResumableManager:
    def __init__(self, state: JumpcloudResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[JumpcloudResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> JumpcloudResumeConfig | None:
        return self._state

    def save_state(self, data: JumpcloudResumeConfig) -> None:
        self.saved.append(data)

    def safe_point(self) -> None:
        pass


def _response_with_status(status_code: int, body: bytes = b"", headers: dict[str, str] | None = None):
    response = requests.Response()
    response.status_code = status_code
    response._content = body
    response.headers.update(headers or {})
    return response


class TestRequest:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_exhaust_retries(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.request.return_value = _response_with_status(status)
        # No-op the backoff sleep so the 5 attempts run instantly.
        with patch.object(jumpcloud._request.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(JumpcloudRetryableError):
                jumpcloud._request(session, "GET", "https://console.jumpcloud.com/api/systemusers", MagicMock())
        assert session.request.call_count == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error_without_retrying(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.request.return_value = _response_with_status(status)
        with pytest.raises(requests.HTTPError):
            jumpcloud._request(session, "GET", "https://console.jumpcloud.com/api/systemusers", MagicMock())
        assert session.request.call_count == 1

    def test_429_carries_server_retry_after(self) -> None:
        session = MagicMock()
        session.request.return_value = _response_with_status(429, headers={"Retry-After": "7"})
        with patch.object(jumpcloud._request.retry, "sleep", lambda *a, **k: None):  # type: ignore[attr-defined]
            with pytest.raises(JumpcloudRetryableError) as exc_info:
                jumpcloud._request(session, "GET", "https://console.jumpcloud.com/api/systemusers", MagicMock())
        assert exc_info.value.retry_after == 7.0

    @parameterized.expand([("moved_permanently", 301), ("temporary_redirect", 307)])
    def test_redirects_are_rejected_not_followed(self, _name: str, status: int) -> None:
        # The session carries the API key in x-api-key; following a redirect would replay it
        # to the redirect target, so the request must refuse redirects entirely.
        session = MagicMock()
        session.request.return_value = _response_with_status(status, headers={"Location": "https://evil.example"})
        with pytest.raises(ValueError):
            jumpcloud._request(session, "GET", "https://console.jumpcloud.com/api/systemusers", MagicMock())
        assert session.request.call_args.kwargs["allow_redirects"] is False


class TestParseSearchAfter:
    @parameterized.expand(
        [
            ("valid_cursor", json.dumps([1747608000000, "abc"]), [1747608000000, "abc"]),
            ("missing_header", None, None),
            ("empty_string", "", None),
            ("garbage", "not-json", None),
            ("non_array", '{"a": 1}', None),
            ("empty_array", "[]", None),
        ]
    )
    def test_parsing(self, _name: str, raw: str | None, expected: list[Any] | None) -> None:
        assert _parse_search_after(raw, MagicMock()) == expected


class TestRestRows:
    @staticmethod
    def _collect(
        endpoint: str,
        pages: list[Any],
        manager: _FakeResumableManager,
        monkeypatch: Any,
        region: str = "us",
    ) -> tuple[list[dict], list[str]]:
        fetched_urls: list[str] = []

        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            assert method == "GET"
            fetched_urls.append(url)
            config = JUMPCLOUD_ENDPOINTS[endpoint]
            skip = int(url.split("skip=")[1].split("&")[0])
            index = skip // (config.page_size or REST_PAGE_SIZE)
            page = pages[index] if index < len(pages) else []
            response = MagicMock()
            if config.api == "v1":
                response.json.return_value = {"totalCount": sum(len(p) for p in pages), "results": page}
            elif config.data_key:
                response.json.return_value = {config.data_key: page, "count": sum(len(p) for p in pages)}
            else:
                response.json.return_value = page
            return response

        monkeypatch.setattr(jumpcloud, "_request", fake_request)
        monkeypatch.setattr(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for page in get_rows(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            region=region,
        ):
            rows.extend(page)
        return rows, fetched_urls

    def test_v1_resumes_from_saved_skip(self, monkeypatch: Any) -> None:
        full_page = [{"_id": str(i)} for i in range(REST_PAGE_SIZE)]
        manager = _FakeResumableManager(JumpcloudResumeConfig(skip=REST_PAGE_SIZE))
        rows, urls = self._collect("users", [full_page, [{"_id": "last"}]], manager, monkeypatch)
        # Resuming at skip=REST_PAGE_SIZE skips the already-synced first page.
        assert rows == [{"_id": "last"}]
        assert len(urls) == 1
        assert f"skip={REST_PAGE_SIZE}" in urls[0]

    @parameterized.expand(
        [
            ("bare_array", "user_groups", "https://console.jumpcloud.com/api/v2/usergroups?"),
            ("wrapped_alerts", "alerts", "https://console.jumpcloud.com/api/v2/alerts?"),
            (
                "wrapped_risk_events",
                "identity_risk_events",
                "https://console.jumpcloud.com/api/v2/identityrisk/events?",
            ),
        ]
    )
    def test_v2_endpoint_rows(self, _name: str, endpoint: str, url_prefix: str) -> None:
        manager = _FakeResumableManager()
        with pytest.MonkeyPatch.context() as monkeypatch:
            rows, urls = self._collect(endpoint, [[{"id": "g1"}]], manager, monkeypatch)
        assert rows == [{"id": "g1"}]
        assert urls[0].startswith(url_prefix)

    def test_system_insights_pages_with_its_larger_page_size(self, monkeypatch: Any) -> None:
        page_size = JUMPCLOUD_ENDPOINTS["system_insights_apps"].page_size
        assert page_size is not None and page_size > REST_PAGE_SIZE
        full_page = [{"system_id": "s1", "name": f"app{i}"} for i in range(page_size)]
        manager = _FakeResumableManager()
        rows, urls = self._collect("system_insights_apps", [full_page, [{"system_id": "s2"}]], manager, monkeypatch)
        assert len(rows) == page_size + 1
        assert [u.split("?")[0] for u in urls] == ["https://console.jumpcloud.com/api/v2/systeminsights/apps"] * 2
        assert f"limit={page_size}" in urls[0]
        assert manager.saved == [JumpcloudResumeConfig(skip=page_size)]

    def test_applications_strips_saml_private_key_before_emitting(self, monkeypatch: Any) -> None:
        # An SSO application row carries its SAML IdP signing key at `config.idpPrivateKey.value`;
        # it must never reach the warehouse, while the rest of the config is kept.
        row = {
            "_id": "app1",
            "name": "Okta",
            "config": {
                "idpPrivateKey": {"value": "-----BEGIN PRIVATE KEY-----secret"},
                "idpEntityId": {"value": "https://idp.example"},
            },
        }
        manager = _FakeResumableManager()
        rows, _ = self._collect("applications", [[row]], manager, monkeypatch)
        assert rows == [
            {
                "_id": "app1",
                "name": "Okta",
                "config": {"idpEntityId": {"value": "https://idp.example"}},
            }
        ]

    @parameterized.expand(
        [
            ("applications", False),
            ("users", True),
            ("application_users", False),
            ("system_users", True),
            ("policy_results", False),
            ("policy_statuses", False),
        ]
    )
    def test_secret_bearing_endpoint_disables_http_sample_capture(self, endpoint: str, expected_capture: bool) -> None:
        # HTTP sample capture writes the raw response body before row-level `redact_keys` runs, so
        # endpoints that redact secrets (applications' SAML key) must opt out of capture entirely.
        capture_kwargs: list[Any] = []

        def fake_make_session(**kwargs: Any) -> Any:
            capture_kwargs.append(kwargs.get("capture"))
            return MagicMock()

        listing = JUMPCLOUD_ENDPOINTS[JUMPCLOUD_ENDPOINTS[endpoint].parent or endpoint]

        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            response = MagicMock()
            response.json.return_value = {"results": []} if listing.api == "v1" else []
            return response

        with (
            patch.object(jumpcloud, "_request", fake_request),
            patch.object(jumpcloud, "make_tracked_session", fake_make_session),
        ):
            list(
                get_rows(
                    api_key="key",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )
        assert capture_kwargs == [expected_capture]

    @parameterized.expand([("v1", "users"), ("v2_wrapped", "alerts")])
    def test_non_wrapped_payload_raises_value_error(self, _name: str, endpoint: str) -> None:
        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            response = MagicMock()
            response.json.return_value = [{"_id": "a"}]  # bare list where the endpoint wraps its rows
            return response

        with (
            patch.object(jumpcloud, "_request", fake_request),
            patch.object(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock()),
            pytest.raises(ValueError),
        ):
            list(
                get_rows(
                    api_key="key",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )


class TestFanoutRows:
    @staticmethod
    def _collect(
        endpoint: str,
        parent_pages: list[list[dict]],
        children: dict[str, list[dict] | int],
        manager: _FakeResumableManager,
        monkeypatch: Any,
    ) -> tuple[list[dict], list[str]]:
        fetched_urls: list[str] = []
        config = JUMPCLOUD_ENDPOINTS[endpoint]
        parent_config = JUMPCLOUD_ENDPOINTS[config.parent or ""]

        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            fetched_urls.append(url)
            path, query = url.removeprefix("https://console.jumpcloud.com").split("?")
            skip = int(query.split("skip=")[1].split("&")[0])
            response = MagicMock()
            if path == parent_config.path:
                index = skip // REST_PAGE_SIZE
                page = parent_pages[index] if index < len(parent_pages) else []
                if parent_config.api == "v1":
                    response.json.return_value = {"results": page}
                elif parent_config.data_key:
                    response.json.return_value = {parent_config.data_key: page}
                else:
                    response.json.return_value = page
                return response
            parent_id = path.split("/")[4]
            child = children.get(parent_id, [])
            if isinstance(child, int):
                raise requests.HTTPError(response=_response_with_status(child))
            child_page = child[skip : skip + REST_PAGE_SIZE]
            response.json.return_value = {config.data_key: child_page} if config.data_key else child_page
            return response

        monkeypatch.setattr(jumpcloud, "_request", fake_request)
        monkeypatch.setattr(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for page in get_rows(
            api_key="key",
            endpoint=endpoint,
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
        ):
            rows.extend(page)
        return rows, fetched_urls

    def test_injects_parent_id_into_each_child_row(self, monkeypatch: Any) -> None:
        member = {"id": "u1", "type": "user", "paths": [[{"to": {"id": "u1", "type": "user"}}]]}
        manager = _FakeResumableManager()
        rows, urls = self._collect(
            "user_group_members",
            [[{"id": "g1"}, {"id": "g2"}]],
            {"g1": [member], "g2": [{"id": "u1", "type": "user", "paths": []}]},
            manager,
            monkeypatch,
        )
        # The same user in two groups must stay two distinct rows under the composite key.
        assert rows == [{**member, "group_id": "g1"}, {"id": "u1", "type": "user", "paths": [], "group_id": "g2"}]
        assert JUMPCLOUD_ENDPOINTS["user_group_members"].primary_keys == ["group_id", "id"]
        assert urls[1].startswith("https://console.jumpcloud.com/api/v2/usergroups/g1/membership?")
        assert manager.saved == []

    def test_reads_v1_parent_ids_and_pages_children(self, monkeypatch: Any) -> None:
        many_users = [{"id": f"u{i}", "type": "user"} for i in range(REST_PAGE_SIZE + 1)]
        manager = _FakeResumableManager()
        rows, urls = self._collect("system_users", [[{"_id": "s1"}]], {"s1": many_users}, manager, monkeypatch)
        assert len(rows) == REST_PAGE_SIZE + 1
        assert {row["system_id"] for row in rows} == {"s1"}
        assert [u.split("?")[0] for u in urls[1:]] == ["https://console.jumpcloud.com/api/v2/systems/s1/users"] * 2

    def test_alert_occurrences_read_wrapped_alerts_and_occurrences(self, monkeypatch: Any) -> None:
        occurrence = {"alertObjectId": "a1", "occurredAt": "2026-01-01T00:00:00Z", "context": {}}
        manager = _FakeResumableManager()
        rows, urls = self._collect(
            "alert_occurrences", [[{"objectId": "a1"}, {"objectId": "a2"}]], {"a1": [occurrence]}, manager, monkeypatch
        )
        assert rows == [{**occurrence, "alert_id": "a1"}]
        assert [u.split("?")[0] for u in urls[1:]] == [
            "https://console.jumpcloud.com/api/v2/alerts/a1/occurrences",
            "https://console.jumpcloud.com/api/v2/alerts/a2/occurrences",
        ]

    def test_checkpoints_parent_offset_after_each_full_parent_page(self, monkeypatch: Any) -> None:
        full_page = [{"_id": f"a{i}"} for i in range(REST_PAGE_SIZE)]
        manager = _FakeResumableManager()
        rows, _ = self._collect(
            "application_users", [full_page, [{"_id": "last"}]], {"last": [{"id": "u1"}]}, manager, monkeypatch
        )
        assert rows == [{"id": "u1", "application_id": "last"}]
        assert manager.saved == [JumpcloudResumeConfig(skip=REST_PAGE_SIZE)]

    def test_resumes_from_saved_parent_offset(self, monkeypatch: Any) -> None:
        full_page = [{"_id": f"a{i}"} for i in range(REST_PAGE_SIZE)]
        manager = _FakeResumableManager(JumpcloudResumeConfig(skip=REST_PAGE_SIZE))
        _, urls = self._collect("application_user_groups", [full_page, [{"_id": "last"}]], {}, manager, monkeypatch)
        assert f"skip={REST_PAGE_SIZE}" in urls[0]
        assert [u.split("?")[0] for u in urls[1:]] == [
            "https://console.jumpcloud.com/api/v2/applications/last/usergroups"
        ]

    def test_parent_deleted_mid_sync_is_skipped(self, monkeypatch: Any) -> None:
        manager = _FakeResumableManager()
        rows, _ = self._collect(
            "system_group_members",
            [[{"id": "gone"}, {"id": "g2"}]],
            {"gone": 404, "g2": [{"id": "s1", "type": "system"}]},
            manager,
            monkeypatch,
        )
        assert rows == [{"id": "s1", "type": "system", "group_id": "g2"}]

    def test_child_permission_error_is_raised(self, monkeypatch: Any) -> None:
        with pytest.raises(requests.HTTPError):
            self._collect("system_users", [[{"_id": "s1"}]], {"s1": 403}, _FakeResumableManager(), monkeypatch)


class TestEventRows:
    @staticmethod
    def _collect(
        manager: _FakeResumableManager,
        monkeypatch: Any,
        pages: list[tuple[list[dict], str | None]],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict], list[dict]]:
        request_bodies: list[dict] = []
        call_index = 0

        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            nonlocal call_index
            assert method == "POST"
            assert url.endswith("/insights/directory/v1/events")
            request_bodies.append(json_body)
            page, search_after_header = pages[call_index] if call_index < len(pages) else ([], None)
            call_index += 1
            response = MagicMock()
            response.json.return_value = page
            response.headers = {"X-Search_After": search_after_header} if search_after_header else {}
            return response

        monkeypatch.setattr(jumpcloud, "_request", fake_request)
        monkeypatch.setattr(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock())

        rows: list[dict] = []
        for page in get_rows(
            api_key="key",
            endpoint="events",
            logger=MagicMock(),
            resumable_source_manager=manager,  # type: ignore[arg-type]
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ):
            rows.extend(page)
        return rows, request_bodies

    def test_follows_search_after_cursor_and_checkpoints_after_yield(self, monkeypatch: Any) -> None:
        full_page = [{"id": str(i)} for i in range(EVENTS_PAGE_SIZE)]
        cursor = [1747608000000, "evt"]
        manager = _FakeResumableManager()
        rows, bodies = self._collect(manager, monkeypatch, [(full_page, json.dumps(cursor)), ([{"id": "last"}], None)])
        assert len(rows) == EVENTS_PAGE_SIZE + 1
        # First request has no cursor; the second carries the header cursor back in the body.
        assert "search_after" not in bodies[0]
        assert bodies[1]["search_after"] == cursor
        # Both pages of one run query the identical pinned window (search_after requires it).
        assert bodies[1]["start_time"] == bodies[0]["start_time"]
        assert bodies[1]["end_time"] == bodies[0]["end_time"]
        assert manager.saved == [
            JumpcloudResumeConfig(
                search_after=cursor, start_time=bodies[0]["start_time"], end_time=bodies[0]["end_time"]
            )
        ]

    def test_resumes_with_saved_window_and_cursor(self, monkeypatch: Any) -> None:
        cursor = [123, "evt"]
        manager = _FakeResumableManager(
            JumpcloudResumeConfig(
                search_after=cursor, start_time="2026-07-01T00:00:00Z", end_time="2026-07-14T00:00:00Z"
            )
        )
        _, bodies = self._collect(manager, monkeypatch, [([{"id": "e2"}], None)])
        assert bodies[0]["search_after"] == cursor
        assert bodies[0]["start_time"] == "2026-07-01T00:00:00Z"
        assert bodies[0]["end_time"] == "2026-07-14T00:00:00Z"

    def test_non_list_payload_raises_value_error(self, monkeypatch: Any) -> None:
        def fake_request(session: Any, method: str, url: str, logger: Any, json_body: Any = None) -> Any:
            response = MagicMock()
            response.json.return_value = {"error": "unexpected"}
            response.headers = {}
            return response

        monkeypatch.setattr(jumpcloud, "_request", fake_request)
        monkeypatch.setattr(jumpcloud, "make_tracked_session", lambda **kwargs: MagicMock())
        with pytest.raises(ValueError):
            list(
                get_rows(
                    api_key="key",
                    endpoint="events",
                    logger=MagicMock(),
                    resumable_source_manager=_FakeResumableManager(),  # type: ignore[arg-type]
                )
            )


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("bad_key", 401, None, False),
            # A 403 at source-create means the key is real but this probe is out of the admin's
            # role — creation must go through.
            ("forbidden_at_create", 403, None, True),
            ("forbidden_for_schema", 403, "users", False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, schema_name: str | None, expected_ok: bool) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(status, body=b"{}")
        with patch.object(jumpcloud, "_make_session", return_value=session):
            ok, _error = validate_credentials("key", schema_name=schema_name)
        assert ok is expected_ok

    def test_events_schema_probes_the_insights_endpoint(self) -> None:
        session = MagicMock()
        session.post.return_value = _response_with_status(200)
        with patch.object(jumpcloud, "_make_session", return_value=session):
            ok, _error = validate_credentials("key", schema_name="events")
        assert ok is True
        url = session.post.call_args.args[0]
        assert url == "https://api.jumpcloud.com/insights/directory/v1/events"
        assert session.post.call_args.kwargs["json"]["limit"] == 1

    def test_fanout_schema_probes_the_parent_listing(self) -> None:
        session = MagicMock()
        session.get.return_value = _response_with_status(200)
        with patch.object(jumpcloud, "_make_session", return_value=session) as make_session:
            ok, _error = validate_credentials("key", schema_name="application_users")
        assert ok is True
        assert session.get.call_args.args[0] == "https://console.jumpcloud.com/api/applications?limit=1"
        # The parent listing carries SAML signing keys, so the probe must not be sample-captured.
        assert make_session.call_args.kwargs["capture"] is False

    def test_connection_error_returns_message(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch.object(jumpcloud, "_make_session", return_value=session):
            ok, error = validate_credentials("key")
        assert ok is False
        assert error is not None


class TestJumpcloudSourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        response = jumpcloud_source(
            api_key="key",
            endpoint=name,
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
        )
        config = JUMPCLOUD_ENDPOINTS[name]
        assert response.name == name
        assert response.primary_keys == config.primary_keys
        # Directory Insights response ordering is undocumented, so the events stream defers
        # its watermark to job end (desc); everything else is plain ascending full refresh.
        assert response.sort_mode == ("desc" if config.api == "insights" else "asc")
        if config.partition_key:
            assert response.partition_keys == [config.partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None

    def test_partition_keys_are_stable_fields(self) -> None:
        # Guards against accidentally partitioning on a churning field like lastContact.
        assert all(
            cfg.partition_key in (None, "created", "createdAt", "startedAt", "timestamp")
            for cfg in JUMPCLOUD_ENDPOINTS.values()
        )
