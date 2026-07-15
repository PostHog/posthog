from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io import fly_io
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.fly_io import (
    FLY_IO_ENDPOINTS,
    _build_url,
    _sanitize_machine,
    fly_io_source,
    get_rows,
    validate_credentials,
)


class TestBuildUrl:
    @parameterized.expand(
        [
            # Org-scoped endpoints carry the org in the path; getting this wrong (leaving the
            # {org_slug} placeholder, or putting the org in a query param) 404s every request.
            ("machines", "https://api.machines.dev/v1/orgs/acme/machines?limit=1000"),
            ("volumes", "https://api.machines.dev/v1/orgs/acme/volumes?limit=1000"),
        ]
    )
    def test_org_scoped_endpoint_puts_org_in_path(self, endpoint: str, expected: str) -> None:
        config = FLY_IO_ENDPOINTS[endpoint]
        url = _build_url(config, "acme", {"limit": 1000})
        assert url == expected

    def test_apps_endpoint_puts_org_in_query(self) -> None:
        # The apps endpoint takes org_slug as a required query param, not a path segment.
        url = _build_url(FLY_IO_ENDPOINTS["apps"], "acme", {})
        assert url == "https://api.machines.dev/v1/apps?org_slug=acme"

    def test_reserved_char_in_slug_is_encoded_in_path(self) -> None:
        # A slug carrying a path-reserved char must be percent-encoded, otherwise it could retarget
        # the request to a different API path than the one credential validation checked.
        url = _build_url(FLY_IO_ENDPOINTS["machines"], "ac/me", {"limit": 1000})
        assert url == "https://api.machines.dev/v1/orgs/ac%2Fme/machines?limit=1000"


class TestValidateCredentials:
    @parameterized.expand(
        [
            (200, True),
            (401, False),
            (403, False),
            (404, False),
            (500, False),
        ]
    )
    def test_status_maps_to_validity(self, status_code: int, expected_valid: bool) -> None:
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"error": "boom"}
        session = MagicMock()
        session.get.return_value = response
        with patch.object(fly_io, "make_tracked_session", return_value=session):
            valid, error = validate_credentials("tok", "acme")
        assert valid is expected_valid
        assert (error is None) is expected_valid

    def test_network_error_is_not_valid(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("no route")
        with patch.object(fly_io, "make_tracked_session", return_value=session):
            valid, error = validate_credentials("tok", "acme")
        assert valid is False
        assert error is not None


class TestFetchPageRetries:
    @parameterized.expand(
        [
            ("rate_limited", 429),
            ("server_error", 503),
        ]
    )
    def test_retryable_status_retries_then_succeeds(self, _name: str, bad_status: int) -> None:
        # A 429/5xx on the first attempt must retry rather than fail the whole sync.
        bad = MagicMock()
        bad.status_code = bad_status
        good = MagicMock()
        good.status_code = 200
        good.ok = True
        good.json.return_value = {"machines": []}
        session = MagicMock()
        session.get.side_effect = [bad, good]

        with patch.object(fly_io._fetch_page.retry, "sleep", lambda *_: None):  # type: ignore[attr-defined]
            result = fly_io._fetch_page(session, "https://api.machines.dev/v1/orgs/a/machines", {}, MagicMock())

        assert result == {"machines": []}
        assert session.get.call_count == 2

    def test_client_error_raises_and_is_not_retried(self) -> None:
        # A 401 is a credential problem — surface it immediately (get_non_retryable_errors handles it),
        # never burn 5 retries on it.
        response = MagicMock()
        response.status_code = 401
        response.ok = False
        response.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=response)
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            fly_io._fetch_page(session, "https://api.machines.dev/v1/orgs/a/machines", {}, MagicMock())
        assert session.get.call_count == 1

    def test_unexpected_response_shape_raises(self) -> None:
        # A bare list where an object wrapper is expected must fail loudly, not silently sync zero rows.
        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = [{"id": "x"}]
        session = MagicMock()
        session.get.return_value = response

        with pytest.raises(ValueError):
            fly_io._fetch_page(session, "https://api.machines.dev/v1/apps", {}, MagicMock())


class TestGetRows:
    @staticmethod
    def _collect(endpoint: str, pages: dict[str, dict[str, Any]]) -> list[dict]:
        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return pages[url]

        rows: list[dict] = []
        with patch.object(fly_io, "make_tracked_session", return_value=MagicMock()):
            with patch.object(fly_io, "_fetch_page", side_effect=fake_fetch):
                for batch in get_rows(api_token="tok", endpoint=endpoint, org_slug="acme", logger=MagicMock()):
                    rows.extend(batch)
        return rows

    def test_apps_is_single_request_and_ignores_cursor(self) -> None:
        # The apps endpoint isn't paginated; a stray next_cursor must not trigger a second request
        # against a cursor the endpoint doesn't accept.
        pages = {
            "https://api.machines.dev/v1/apps?org_slug=acme": {
                "apps": [{"id": "app1"}, {"id": "app2"}],
                "next_cursor": "should-be-ignored",
            },
        }
        assert self._collect("apps", pages) == [{"id": "app1"}, {"id": "app2"}]

    def test_machines_follows_cursor_until_exhausted(self) -> None:
        # Not advancing the cursor loops forever; not following it silently drops later pages.
        pages = {
            "https://api.machines.dev/v1/orgs/acme/machines?limit=1000": {
                "machines": [{"id": "m1", "app_name": "app1"}],
                "next_cursor": "c2",
            },
            "https://api.machines.dev/v1/orgs/acme/machines?limit=1000&cursor=c2": {
                "machines": [{"id": "m2", "app_name": "app2"}],
                "next_cursor": "",
            },
        }
        rows = self._collect("machines", pages)
        assert [r["id"] for r in rows] == ["m1", "m2"]

    def test_empty_response_yields_no_rows(self) -> None:
        pages: dict[str, dict[str, Any]] = {
            "https://api.machines.dev/v1/orgs/acme/volumes?limit=1000": {"volumes": [], "next_cursor": None},
        }
        assert self._collect("volumes", pages) == []


class TestMachineSecretRedaction:
    def test_sanitize_strips_secret_bearing_config_fields(self) -> None:
        # env, files (inline file contents), and secrets would land deployment credentials in the
        # warehouse where any project member with query access could read them — they must be dropped.
        row = {
            "id": "m1",
            "config": {
                "image": "flyio/app:latest",
                "guest": {"cpus": 1, "memory_mb": 256},
                "env": {"DATABASE_URL": "postgres://user:pass@host/db"},
                "secrets": [{"name": "STRIPE_KEY"}],
                "files": [{"guest_path": "/etc/cert.pem", "raw_value": "c3VwZXItc2VjcmV0"}],
                "processes": [
                    {"cmd": ["run"], "env": {"TOKEN": "shhh"}, "secrets": [{"name": "X"}]},
                ],
            },
        }
        sanitized = _sanitize_machine(row)
        config = sanitized["config"]
        assert config["image"] == "flyio/app:latest"
        assert config["guest"] == {"cpus": 1, "memory_mb": 256}
        assert "env" not in config
        assert "secrets" not in config
        assert "files" not in config
        # Processes stay (cmd is operational) but their nested secret vectors are stripped.
        assert config["processes"] == [{"cmd": ["run"]}]
        # The original row is not mutated in place.
        assert "env" in row["config"]

    def test_sanitize_keeps_only_platform_metadata_keys(self) -> None:
        # Fly metadata is a free-form user map, so a user-set secret must not survive; only Fly's
        # own platform keys are known-safe and kept.
        row = {
            "id": "m1",
            "config": {
                "image": "app",
                "metadata": {
                    "fly_process_group": "web",
                    "fly_release_id": "rel_123",
                    "api_token": "FlyV1 super-secret",
                    "DATABASE_PASSWORD": "hunter2",
                },
            },
        }
        metadata = _sanitize_machine(row)["config"]["metadata"]
        assert metadata == {"fly_process_group": "web", "fly_release_id": "rel_123"}

    def test_sanitize_strips_request_headers_from_services_and_checks(self) -> None:
        # Service/check request headers can carry an Authorization credential, so every nested
        # `headers` map must be dropped while the rest of the networking config is kept.
        row = {
            "id": "m1",
            "config": {
                "image": "app",
                "services": [
                    {
                        "internal_port": 8080,
                        "checks": [
                            {
                                "type": "http",
                                "path": "/health",
                                "headers": [{"name": "Authorization", "value": "Bearer secret"}],
                            }
                        ],
                    }
                ],
                "checks": {"web": {"type": "http", "path": "/", "headers": [{"name": "X-Token", "value": "shhh"}]}},
            },
        }
        config = _sanitize_machine(row)["config"]
        assert config["services"] == [{"internal_port": 8080, "checks": [{"type": "http", "path": "/health"}]}]
        assert config["checks"] == {"web": {"type": "http", "path": "/"}}

    def test_sanitize_leaves_row_without_config_untouched(self) -> None:
        row = {"id": "m1", "state": "started"}
        assert _sanitize_machine(row) == row

    def test_machines_stream_sanitizes_rows_and_disables_sample_capture(self) -> None:
        # End-to-end wiring: the machines stream must both redact secrets from every yielded row and
        # opt out of HTTP sample capture, so secrets reach neither the warehouse nor the sample pipeline.
        pages = {
            "https://api.machines.dev/v1/orgs/acme/machines?limit=1000": {
                "machines": [{"id": "m1", "config": {"image": "app", "env": {"SECRET": "x"}}}],
                "next_cursor": None,
            },
        }

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return pages[url]

        rows: list[dict] = []
        with patch.object(fly_io, "make_tracked_session", return_value=MagicMock()) as mock_session:
            with patch.object(fly_io, "_fetch_page", side_effect=fake_fetch):
                for batch in get_rows(api_token="tok", endpoint="machines", org_slug="acme", logger=MagicMock()):
                    rows.extend(batch)

        assert rows == [{"id": "m1", "config": {"image": "app"}}]
        mock_session.assert_called_once_with(capture=False)

    def test_non_secret_stream_keeps_sample_capture_and_rows_verbatim(self) -> None:
        # Volumes carry no secrets, so their session must keep capture on and rows pass through unchanged.
        pages = {
            "https://api.machines.dev/v1/orgs/acme/volumes?limit=1000": {
                "volumes": [{"id": "v1", "encrypted": True}],
                "next_cursor": None,
            },
        }

        def fake_fetch(session: Any, url: str, headers: dict[str, str], logger: Any) -> dict:
            return pages[url]

        rows: list[dict] = []
        with patch.object(fly_io, "make_tracked_session", return_value=MagicMock()) as mock_session:
            with patch.object(fly_io, "_fetch_page", side_effect=fake_fetch):
                for batch in get_rows(api_token="tok", endpoint="volumes", org_slug="acme", logger=MagicMock()):
                    rows.extend(batch)

        assert rows == [{"id": "v1", "encrypted": True}]
        mock_session.assert_called_once_with(capture=True)


class TestFlyIoSourceResponse:
    @parameterized.expand(
        [
            ("machines", "created_at"),
            ("volumes", "created_at"),
        ]
    )
    def test_timestamped_endpoints_partition_on_created_at(self, endpoint: str, partition_key: str) -> None:
        response = fly_io_source(api_token="tok", endpoint=endpoint, org_slug="acme", logger=MagicMock())
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [partition_key]
        assert response.primary_keys == ["id"]

    def test_apps_has_no_partitioning(self) -> None:
        # App objects carry no timestamp, so partitioning on a nonexistent column would break the sync.
        response = fly_io_source(api_token="tok", endpoint="apps", org_slug="acme", logger=MagicMock())
        assert response.partition_mode is None
        assert response.partition_keys is None
        assert response.primary_keys == ["id"]
