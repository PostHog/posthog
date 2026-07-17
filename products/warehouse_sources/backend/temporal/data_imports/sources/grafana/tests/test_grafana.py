from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.grafana import grafana as grafana_module
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.grafana import (
    ANNOTATIONS_LIMIT,
    BASIC_AUTH,
    DEFAULT_PAGE_SIZE,
    TOKEN_AUTH,
    GrafanaAuth,
    GrafanaAuthError,
    GrafanaResumeConfig,
    _extract_items,
    _permission_error_from_response,
    _resolve_auth_headers,
    get_endpoint_permissions,
    get_rows,
    grafana_source,
    normalize_host,
    validate_credentials,
)


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.text = text
    response.json.return_value = json_data
    response.headers = {}
    return response


def _token_auth() -> GrafanaAuth:
    return GrafanaAuth(method=TOKEN_AUTH, token="glsa_secret")


def _basic_auth() -> GrafanaAuth:
    return GrafanaAuth(method=BASIC_AUTH, username="admin", password="hunter2")


class FakeResumableManager:
    def __init__(self, state: GrafanaResumeConfig | None = None):
        self.state = state
        self.saved: list[GrafanaResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> GrafanaResumeConfig | None:
        return self.state

    def save_state(self, state: GrafanaResumeConfig) -> None:
        self.saved.append(state)
        self.state = state


def _patch_session(session: mock.MagicMock):
    return mock.patch.object(grafana_module, "make_tracked_session", return_value=session)


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://yourstack.grafana.net", "https://yourstack.grafana.net"),
            ("yourstack.grafana.net", "https://yourstack.grafana.net"),
            ("https://yourstack.grafana.net/", "https://yourstack.grafana.net"),
            ("https://yourstack.grafana.net/api", "https://yourstack.grafana.net"),
            ("  yourstack.grafana.net  ", "https://yourstack.grafana.net"),
            ("http://localhost:3000", "http://localhost:3000"),
            ("http://127.0.0.1:3000", "http://127.0.0.1:3000"),
            # Plaintext HTTP to a remote host is upgraded to HTTPS so credentials aren't sent in the clear.
            ("http://grafana.mycompany.com", "https://grafana.mycompany.com"),
            ("HTTP://grafana.mycompany.com/api", "https://grafana.mycompany.com"),
            # URL-embedded credentials are stripped so they're never persisted or sent.
            ("https://admin:hunter2@grafana.mycompany.com", "https://grafana.mycompany.com"),
            ("https://admin:hunter2@grafana.mycompany.com:3000/api", "https://grafana.mycompany.com:3000"),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestResolveAuthHeaders:
    def test_token_auth_sends_bearer(self):
        headers = _resolve_auth_headers(_token_auth())
        assert headers["Authorization"] == "Bearer glsa_secret"

    def test_basic_auth_sends_base64_credentials(self):
        headers = _resolve_auth_headers(_basic_auth())
        # base64("admin:hunter2")
        assert headers["Authorization"] == "Basic YWRtaW46aHVudGVyMg=="

    def test_org_id_header_set_when_provided(self):
        headers = _resolve_auth_headers(_token_auth(), org_id="2")
        assert headers["X-Grafana-Org-Id"] == "2"

    @pytest.mark.parametrize("org_id", [None, "", "  "])
    def test_org_id_header_omitted_when_blank(self, org_id):
        headers = _resolve_auth_headers(_token_auth(), org_id=org_id)
        assert "X-Grafana-Org-Id" not in headers

    @pytest.mark.parametrize(
        "auth",
        [
            GrafanaAuth(method=TOKEN_AUTH, token=None),
            GrafanaAuth(method=BASIC_AUTH, username="admin", password=None),
            GrafanaAuth(method=BASIC_AUTH, username=None, password="pw"),
        ],
    )
    def test_missing_credentials_raise_auth_error(self, auth):
        with pytest.raises(GrafanaAuthError):
            _resolve_auth_headers(auth)


class TestExtractItems:
    @pytest.mark.parametrize(
        "data, data_key, expected",
        [
            ([{"id": 1}, {"id": 2}], None, [{"id": 1}, {"id": 2}]),
            ([{"id": 1}, "skip-me", 5], None, [{"id": 1}]),
            ({"teams": [{"id": 1}], "totalCount": 1}, "teams", [{"id": 1}]),
            ({"totalCount": 0}, "teams", []),
            (None, None, []),
            ("nonsense", None, []),
            ({"teams": "nonsense"}, "teams", []),
        ],
    )
    def test_extract_items(self, data, data_key, expected):
        assert _extract_items(data, data_key) == expected


class TestPermissionErrorParsing:
    def test_parses_named_scope_from_403_body(self):
        response = _response(
            status_code=403,
            json_data={
                "message": "You'll need additional permissions to perform this action. Permissions needed: teams:read"
            },
        )
        assert "teams:read" in _permission_error_from_response(response)

    def test_falls_back_to_generic_message(self):
        response = _response(status_code=403, json_data={"message": "Access denied"})
        message = _permission_error_from_response(response)
        assert "permission" in message.lower()
        assert "Access denied" not in message


class TestValidateCredentials:
    def test_valid_credentials(self):
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=200, json_data={"id": 1, "name": "Main Org."})
        with _patch_session(session):
            assert validate_credentials("https://x.grafana.net", _token_auth()) == (True, None)
            assert session.get.call_args.args[0] == "https://x.grafana.net/api/org"
            assert session.get.call_args.kwargs["allow_redirects"] is False

    def test_invalid_credentials(self):
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=401, json_data={"message": "Unauthorized"})
        with _patch_session(session):
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth())
            assert valid is False
            assert msg == "Invalid Grafana credentials"

    def test_403_passes_at_source_create_but_fails_for_schema(self):
        # An under-scoped (but genuine) token must not block source creation — per-endpoint scope
        # is reported separately — yet must fail a per-schema check.
        session = mock.MagicMock()
        session.get.return_value = _response(
            status_code=403,
            json_data={"message": "You'll need additional permissions. Permissions needed: orgs:read"},
        )
        with _patch_session(session):
            assert validate_credentials("https://x.grafana.net", _token_auth()) == (True, None)

            valid, msg = validate_credentials("https://x.grafana.net", _token_auth(), schema_name="teams")
            assert valid is False
            assert msg is not None and "orgs:read" in msg

    def test_rejects_redirect_response(self):
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=302)
        with _patch_session(session):
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth())
            assert valid is False
            assert msg == grafana_module.HOST_NOT_ALLOWED_ERROR

    def test_blocks_unsafe_host(self):
        session = mock.MagicMock()
        with (
            mock.patch.object(grafana_module, "_is_host_safe", return_value=(False, "internal address")),
            _patch_session(session),
        ):
            valid, msg = validate_credentials("https://10.0.0.1", _token_auth(), team_id=99)
            assert valid is False
            assert msg == "internal address"
            session.get.assert_not_called()

    @pytest.mark.parametrize(
        "host",
        ["https://admin:hunter2@grafana.mycompany.com", "admin:hunter2@grafana.mycompany.com"],
    )
    def test_rejects_url_embedded_credentials(self, host):
        # The host field is stored as non-secret config, so a password embedded in the URL would
        # be exposed to anyone who can view the source configuration.
        session = mock.MagicMock()
        with _patch_session(session):
            valid, msg = validate_credentials(host, _token_auth())
            assert valid is False
            assert msg is not None
            assert "hunter2" not in msg
            session.get.assert_not_called()

    def test_missing_token_surfaces_before_probe(self):
        session = mock.MagicMock()
        with _patch_session(session):
            valid, msg = validate_credentials("https://x.grafana.net", GrafanaAuth(method=TOKEN_AUTH, token=None))
            assert valid is False
            assert msg == "Missing Grafana service account token"
            session.get.assert_not_called()

    def test_connection_error_does_not_leak_host(self):
        raw = "HTTPSConnectionPool(host='203.0.113.10', port=443): Max retries exceeded"
        session = mock.MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError(raw)
        with _patch_session(session):
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth())
            assert valid is False
            assert msg is not None
            assert "203.0.113.10" not in msg
            assert "HTTPSConnectionPool" not in msg

    def test_unexpected_status_does_not_leak_response_body(self):
        leaked_body = '{"error": "SENTINEL_UPSTREAM_BODY"}'
        session = mock.MagicMock()
        session.get.return_value = _response(status_code=404, json_data={"error": "x"}, text=leaked_body)
        with _patch_session(session):
            valid, msg = validate_credentials("https://x.grafana.net", _token_auth())
            assert valid is False
            assert msg is not None
            assert "SENTINEL_UPSTREAM_BODY" not in msg
            assert "404" in msg


class TestGetEndpointPermissions:
    def test_maps_status_codes_to_reasons(self):
        def get(url, **kwargs):
            if "/api/teams/search" in url:
                return _response(status_code=403, json_data={"message": "Permissions needed: teams:read"})
            return _response(status_code=200, json_data=[])

        session = mock.MagicMock()
        session.get.side_effect = get
        with _patch_session(session):
            results = get_endpoint_permissions("https://x.grafana.net", _token_auth(), None, 1, ["dashboards", "teams"])
        assert results["dashboards"] is None
        assert results["teams"] is not None and "teams:read" in results["teams"]

    def test_network_blip_is_not_a_missing_scope(self):
        session = mock.MagicMock()
        session.get.side_effect = requests.exceptions.ConnectionError("boom")
        with _patch_session(session):
            results = get_endpoint_permissions("https://x.grafana.net", _token_auth(), None, 1, ["dashboards"])
        assert results == {"dashboards": None}


class TestPagedRows:
    def _run(self, endpoint: str, responses: list[Any], manager: FakeResumableManager | None = None):
        manager = manager or FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = [_response(status_code=200, json_data=r) for r in responses]
        with (
            _patch_session(session),
            mock.patch.object(grafana_module, "_is_host_safe", return_value=(True, None)),
        ):
            batches = list(
                get_rows(
                    host="https://x.grafana.net",
                    auth=_token_auth(),
                    org_id=None,
                    endpoint=endpoint,
                    logger=mock.MagicMock(),
                    team_id=1,
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                )
            )
        return batches, session, manager

    def test_stops_after_partial_page(self):
        full_page = [{"uid": f"d{i}"} for i in range(DEFAULT_PAGE_SIZE)]
        partial_page = [{"uid": "last"}]
        batches, session, manager = self._run("dashboards", [full_page, partial_page])

        assert len(batches) == 2
        assert batches[1] == partial_page
        assert session.get.call_count == 2
        assert _query(session.get.call_args_list[0].args[0])["page"] == "1"
        assert _query(session.get.call_args_list[1].args[0])["page"] == "2"
        # Resume state advances only past completed full pages, so a crash re-yields (never skips).
        assert [s.next_page for s in manager.saved] == [2]

    def test_empty_first_page_yields_nothing(self):
        batches, session, _ = self._run("folders", [[]])
        assert batches == []
        assert session.get.call_count == 1

    def test_dashboards_search_params(self):
        batches, session, _ = self._run("dashboards", [[{"uid": "d1"}]])
        query = _query(session.get.call_args.args[0])
        assert query["type"] == "dash-db"
        assert query["limit"] == str(DEFAULT_PAGE_SIZE)
        assert urlparse(session.get.call_args.args[0]).path == "/api/search"

    def test_wrapped_endpoint_extracts_rows(self):
        batches, session, _ = self._run("teams", [{"teams": [{"id": 7}], "totalCount": 1}])
        assert batches == [[{"id": 7}]]
        assert _query(session.get.call_args.args[0])["perpage"] == str(DEFAULT_PAGE_SIZE)

    def test_resumes_from_saved_page(self):
        manager = FakeResumableManager(GrafanaResumeConfig(next_page=3))
        batches, session, _ = self._run("dashboards", [[{"uid": "d1"}]], manager=manager)
        assert _query(session.get.call_args.args[0])["page"] == "3"

    def test_unpaginated_endpoint_single_request(self):
        batches, session, _ = self._run("datasources", [[{"uid": "ds1"}, {"uid": "ds2"}]])
        assert batches == [[{"uid": "ds1"}, {"uid": "ds2"}]]
        assert session.get.call_count == 1
        assert "page" not in _query(session.get.call_args.args[0])


class TestAnnotationRows:
    def _run(
        self,
        get_side_effect,
        manager: FakeResumableManager | None = None,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ):
        manager = manager or FakeResumableManager()
        session = mock.MagicMock()
        session.get.side_effect = get_side_effect
        with (
            _patch_session(session),
            mock.patch.object(grafana_module, "_is_host_safe", return_value=(True, None)),
        ):
            batches = list(
                get_rows(
                    host="https://x.grafana.net",
                    auth=_token_auth(),
                    org_id=None,
                    endpoint="annotations",
                    logger=mock.MagicMock(),
                    team_id=1,
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return batches, session, manager

    def test_single_unsaturated_window(self):
        rows = [{"id": 1, "time": 100}, {"id": 2, "time": 50}]
        batches, session, manager = self._run([_response(status_code=200, json_data=rows)])

        assert batches == [rows]
        assert session.get.call_count == 1
        query = _query(session.get.call_args.args[0])
        assert query["type"] == "annotation"
        assert query["from"] == "0"
        assert query["limit"] == str(ANNOTATIONS_LIMIT)
        # Final window completes the walk — no resume state to leave behind.
        assert manager.saved == []

    def test_saturated_window_bisects_oldest_first(self):
        saturated = [{"id": i, "time": i} for i in range(ANNOTATIONS_LIMIT)]
        left_rows = [{"id": 1, "time": 10}]
        right_rows = [{"id": 2, "time": 20}]
        calls: list[tuple[int, int]] = []

        def get(url, **kwargs):
            query = _query(url)
            window = (int(query["from"]), int(query["to"]))
            calls.append(window)
            if len(calls) == 1:
                return _response(status_code=200, json_data=saturated)
            return _response(status_code=200, json_data=left_rows if len(calls) == 2 else right_rows)

        batches, _, manager = self._run(get)

        assert batches == [left_rows, right_rows]
        first_from, first_to = calls[0]
        mid = (first_from + first_to) // 2
        # Halves cover the full original window (sharing the mid boundary) and run oldest-first.
        assert calls[1] == (first_from, mid)
        assert calls[2] == (mid, first_to)
        # After the older half yields, the resume boundary advances to its upper bound.
        assert [s.annotations_from_ms for s in manager.saved] == [mid]

    def test_incremental_watermark_becomes_from_param(self):
        batches, session, _ = self._run(
            [_response(status_code=200, json_data=[{"id": 3, "time": 1700000000500}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000000,
        )
        assert _query(session.get.call_args.args[0])["from"] == "1700000000000"

    def test_full_refresh_ignores_watermark(self):
        batches, session, _ = self._run(
            [_response(status_code=200, json_data=[])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        assert _query(session.get.call_args.args[0])["from"] == "0"

    def test_resumes_from_saved_boundary(self):
        manager = FakeResumableManager(GrafanaResumeConfig(annotations_from_ms=5_000_000))
        batches, session, _ = self._run([_response(status_code=200, json_data=[])], manager=manager)
        assert _query(session.get.call_args.args[0])["from"] == "5000000"

    def test_future_watermark_fetches_nothing(self):
        # A watermark at/past "now" leaves no window to walk; the sync must no-op, not error.
        far_future_ms = 4102444800000  # 2100-01-01
        batches, session, _ = self._run(
            [],
            should_use_incremental_field=True,
            db_incremental_field_last_value=far_future_ms,
        )
        assert batches == []
        session.get.assert_not_called()


class TestGrafanaSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, sort_mode",
        [
            ("dashboards", ["uid"], "asc"),
            ("folders", ["uid"], "asc"),
            ("teams", ["id"], "asc"),
            ("users", ["userId"], "asc"),
            ("datasources", ["uid"], "asc"),
            ("service_accounts", ["id"], "asc"),
            ("alert_rules", ["uid"], "asc"),
            ("annotations", ["id"], "desc"),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, sort_mode):
        response = grafana_source(
            host="https://x.grafana.net",
            auth=_token_auth(),
            org_id=None,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            team_id=1,
            resumable_source_manager=FakeResumableManager(),  # type: ignore[arg-type]
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
