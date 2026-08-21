from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.healthchecks import (
    DEFAULT_BASE_URL,
    HealthchecksResumeConfig,
    HealthchecksRetryableError,
    _check_key,
    _fetch,
    _to_unix_seconds,
    get_rows,
    healthchecks_source,
    hostname_of,
    normalize_base_url,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.healthchecks.healthchecks"


def _make_manager(resume_state: HealthchecksResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.text = str(body)
    return resp


def _routing_session(routes: dict[str, mock.MagicMock]) -> mock.MagicMock:
    """A fake session whose .get(url) returns the response whose route substring matches the URL."""

    def _get(url: str, **_: Any) -> mock.MagicMock:
        # Match on the path (drop any query string) by suffix, so "/checks/u-1/flips/" routes to
        # flips rather than the "/checks/" list endpoint that shares its prefix.
        path = url.split("?", 1)[0]
        for fragment in sorted(routes, key=len, reverse=True):
            if path.endswith(fragment):
                return routes[fragment]
        raise AssertionError(f"No route registered for URL: {url}")

    session = mock.MagicMock()
    session.get.side_effect = _get
    return session


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, DEFAULT_BASE_URL),
            ("", DEFAULT_BASE_URL),
            ("   ", DEFAULT_BASE_URL),
            ("https://healthchecks.io", "https://healthchecks.io"),
            ("healthchecks.example.com", "https://healthchecks.example.com"),
            ("https://hc.example.com/", "https://hc.example.com"),
            ("http://hc.internal:8000", "http://hc.internal:8000"),
        ],
    )
    def test_valid(self, value, expected):
        assert normalize_base_url(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "ftp://example.com",
            "https://",
            # SSRF host-confusion tricks: the parsed hostname (validated by the SSRF allowlist)
            # must not diverge from the host the HTTP client dials. Reject backslashes (raw and
            # encoded), userinfo, and query/fragment so the allowlist can't be bypassed.
            "http://169.254.169.254\\@example.com/",
            "http://169.254.169.254%5c@example.com/",
            "http://user@169.254.169.254",
            "http://example.com@169.254.169.254",
            "https://example.com?@169.254.169.254",
            "https://example.com#@169.254.169.254",
        ],
    )
    def test_invalid_raises(self, value):
        with pytest.raises(ValueError):
            normalize_base_url(value)

    def test_hostname_of_default(self):
        assert hostname_of(None) == "healthchecks.io"


class TestToUnixSeconds:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.5, 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            # Naive datetimes are treated as UTC.
            (datetime(2023, 11, 14, 22, 13, 20), 1700000000),
            ("2023-11-14T22:13:20Z", 1700000000),
            ("2023-11-14T22:13:20+00:00", 1700000000),
            ("not-a-date", None),
        ],
    )
    def test_conversion(self, value, expected):
        assert _to_unix_seconds(value) == expected

    def test_date_conversion(self):
        assert _to_unix_seconds(date(2023, 11, 14)) == int(datetime(2023, 11, 14, tzinfo=UTC).timestamp())


class TestCheckKey:
    def test_prefers_uuid(self):
        assert _check_key({"uuid": "u-1", "unique_key": "k-1"}) == "u-1"

    def test_falls_back_to_unique_key(self):
        assert _check_key({"unique_key": "k-1"}) == "k-1"

    def test_none_when_absent(self):
        assert _check_key({"name": "x"}) is None


class TestFetch:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retryable_statuses_raise(self, status_code):
        session = mock.MagicMock()
        session.get.return_value = _response({}, status_code=status_code)
        # Skip tenacity's real backoff sleeps so the retry exhausts instantly.
        _fetch.retry.sleep = lambda *_: None  # type: ignore[attr-defined]
        with pytest.raises(HealthchecksRetryableError):
            _fetch(session, "https://healthchecks.io/api/v3/checks/", {}, mock.MagicMock())
        # 5 attempts (stop_after_attempt) before it gives up and reraises.
        assert session.get.call_count == 5

    def test_client_error_raises_for_status(self):
        session = mock.MagicMock()
        resp = _response({"error": "missing api key"}, status_code=401)
        resp.raise_for_status.side_effect = requests.HTTPError(
            "401 Client Error: Unauthorized for url", response=requests.Response()
        )
        session.get.return_value = resp
        with pytest.raises(requests.HTTPError):
            _fetch(session, "https://healthchecks.io/api/v3/checks/", {}, mock.MagicMock())


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid(self, mock_session):
        mock_session.return_value.get.return_value = _response({"checks": []})
        assert validate_credentials(None, "key") == (True, None)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_key(self, mock_session):
        mock_session.return_value.get.return_value = _response({"error": "wrong api key"}, status_code=401)
        ok, err = validate_credentials(None, "bad")
        assert ok is False
        assert err == "Invalid Healthchecks API key"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_error(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        ok, err = validate_credentials(None, "key")
        assert ok is False
        assert "boom" in (err or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_disables_sample_capture(self, mock_session):
        # The checks response carries uuid/ping_url (ping credentials); the session must keep it
        # out of the HTTP sample store.
        mock_session.return_value.get.return_value = _response({"checks": []})
        validate_credentials(None, "key")
        assert mock_session.call_args.kwargs["capture"] is False


class TestGetRowsTopLevel:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_checks_normalizes_id_from_uuid(self, mock_session):
        mock_session.return_value = _routing_session(
            {"/checks/": _response({"checks": [{"uuid": "u-1", "name": "job"}]})}
        )
        rows = list(get_rows(None, "key", "checks", mock.MagicMock(), _make_manager()))
        assert rows == [[{"id": "u-1", "uuid": "u-1", "name": "job"}]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_checks_normalizes_id_from_unique_key(self, mock_session):
        # Read-only keys omit uuid and expose unique_key; id must still be populated.
        mock_session.return_value = _routing_session(
            {"/checks/": _response({"checks": [{"unique_key": "k-1", "name": "job"}]})}
        )
        rows = list(get_rows(None, "key", "checks", mock.MagicMock(), _make_manager()))
        assert rows[0][0]["id"] == "k-1"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_channels(self, mock_session):
        mock_session.return_value = _routing_session(
            {"/channels/": _response({"channels": [{"id": "c-1", "kind": "email"}]})}
        )
        rows = list(get_rows(None, "key", "channels", mock.MagicMock(), _make_manager()))
        assert rows == [[{"id": "c-1", "kind": "email"}]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_yields_nothing(self, mock_session):
        mock_session.return_value = _routing_session({"/channels/": _response({"channels": []})})
        assert list(get_rows(None, "key", "channels", mock.MagicMock(), _make_manager())) == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_disables_sample_capture(self, mock_session):
        # The checks response carries uuid/ping_url (ping credentials); the session must keep it
        # out of the HTTP sample store.
        mock_session.return_value = _routing_session({"/checks/": _response({"checks": []})})
        list(get_rows(None, "key", "checks", mock.MagicMock(), _make_manager()))
        assert mock_session.call_args.kwargs["capture"] is False


class TestGetRowsFanOut:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_flips_injects_check_id_and_bare_array(self, mock_session):
        mock_session.return_value = _routing_session(
            {
                "/checks/": _response({"checks": [{"uuid": "u-1"}]}),
                "/checks/u-1/flips/": _response([{"timestamp": "2023-11-14T22:13:20+00:00", "up": 1}]),
            }
        )
        rows = list(get_rows(None, "key", "flips", mock.MagicMock(), _make_manager()))
        assert rows == [[{"check_id": "u-1", "timestamp": "2023-11-14T22:13:20+00:00", "up": 1}]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_flips_incremental_passes_start_param(self, mock_session):
        session = _routing_session(
            {
                "/checks/": _response({"checks": [{"uuid": "u-1"}]}),
                "/flips/": _response([]),
            }
        )
        mock_session.return_value = session
        list(
            get_rows(
                None,
                "key",
                "flips",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC),
            )
        )
        flip_call = next(c for c in session.get.call_args_list if "/flips/" in c.args[0])
        assert "start=1700000000" in flip_call.args[0]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_flips_no_incremental_omits_start(self, mock_session):
        session = _routing_session({"/checks/": _response({"checks": [{"uuid": "u-1"}]}), "/flips/": _response([])})
        mock_session.return_value = session
        list(get_rows(None, "key", "flips", mock.MagicMock(), _make_manager()))
        flip_call = next(c for c in session.get.call_args_list if "/flips/" in c.args[0])
        assert "start=" not in flip_call.args[0]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pings_404_is_skipped(self, mock_session):
        # A read-only key can't address the pings sub-endpoint (needs the full uuid) -> 404 skip.
        not_found = _response({}, status_code=404)
        not_found.raise_for_status.side_effect = requests.HTTPError(response=not_found)
        mock_session.return_value = _routing_session(
            {
                "/checks/": _response({"checks": [{"unique_key": "k-1"}]}),
                "/checks/k-1/pings/": not_found,
            }
        )
        rows = list(get_rows(None, "key", "pings", mock.MagicMock(), _make_manager()))
        assert rows == []

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_pings_injects_check_id(self, mock_session):
        mock_session.return_value = _routing_session(
            {
                "/checks/": _response({"checks": [{"uuid": "u-1"}]}),
                "/checks/u-1/pings/": _response({"pings": [{"n": 5, "type": "success"}]}),
            }
        )
        rows = list(get_rows(None, "key", "pings", mock.MagicMock(), _make_manager()))
        assert rows == [[{"check_id": "u-1", "n": 5, "type": "success"}]]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fan_out_redacts_check_keys_and_disables_capture(self, mock_session):
        # Each fan-out URL puts a check key in its path, and a check key doubles as a ping
        # credential, so the fan-out session must redact the keys from request telemetry (and
        # keep response bodies out of the sample store).
        mock_session.return_value = _routing_session(
            {
                "/checks/": _response({"checks": [{"uuid": "u-1"}, {"uuid": "u-2"}]}),
                "/checks/u-1/flips/": _response([]),
                "/checks/u-2/flips/": _response([]),
            }
        )
        list(get_rows(None, "key", "flips", mock.MagicMock(), _make_manager()))
        assert all(c.kwargs["capture"] is False for c in mock_session.call_args_list)
        # The fan-out session is built last, once the per-check keys are known.
        fan_out_call = mock_session.call_args_list[-1]
        assert set(fan_out_call.kwargs["redact_values"]) == {"key", "u-1", "u-2"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fan_out_resumes_from_bookmark(self, mock_session):
        # Two checks; resume bookmarked at the second, so only it is fetched.
        session = _routing_session(
            {
                "/checks/": _response({"checks": [{"uuid": "u-1"}, {"uuid": "u-2"}]}),
                "/checks/u-2/flips/": _response([{"timestamp": "2023-01-01T00:00:00+00:00", "up": 0}]),
            }
        )
        mock_session.return_value = session
        manager = _make_manager(HealthchecksResumeConfig(check_key="u-2"))
        rows = list(get_rows(None, "key", "flips", mock.MagicMock(), manager))
        assert rows == [[{"check_id": "u-2", "timestamp": "2023-01-01T00:00:00+00:00", "up": 0}]]
        fetched = [c.args[0] for c in session.get.call_args_list]
        assert not any("/checks/u-1/flips/" in u for u in fetched)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fan_out_bookmarks_next_check_after_completing_current(self, mock_session):
        # After finishing u-1 the bookmark advances to u-2, so a resume skips the already-yielded
        # u-1 rather than re-emitting them. The final check saves nothing (nothing left to resume).
        mock_session.return_value = _routing_session(
            {
                "/checks/": _response({"checks": [{"uuid": "u-1"}, {"uuid": "u-2"}]}),
                "/checks/u-1/flips/": _response([{"timestamp": "2023-01-01T00:00:00+00:00", "up": 1}]),
                "/checks/u-2/flips/": _response([{"timestamp": "2023-01-02T00:00:00+00:00", "up": 0}]),
            }
        )
        manager = _make_manager()
        list(get_rows(None, "key", "flips", mock.MagicMock(), manager))
        saved = [c.args[0].check_key for c in manager.save_state.call_args_list]
        assert saved == ["u-2"]


class TestHealthchecksSource:
    @pytest.mark.parametrize(
        "endpoint, expected_keys, expected_sort, has_partition",
        [
            ("checks", ["id"], "asc", False),
            ("channels", ["id"], "asc", False),
            ("flips", ["check_id", "timestamp"], "desc", True),
            ("pings", ["check_id", "n"], "asc", True),
        ],
    )
    def test_source_response_shape(self, endpoint, expected_keys, expected_sort, has_partition):
        response = healthchecks_source(None, "key", endpoint, mock.MagicMock(), _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == expected_keys
        assert response.sort_mode == expected_sort
        if has_partition:
            assert response.partition_mode == "datetime"
            assert response.partition_keys is not None
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
