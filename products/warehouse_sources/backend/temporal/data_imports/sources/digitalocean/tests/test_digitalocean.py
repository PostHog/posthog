import json
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean import (
    _paginator,
    digitalocean_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.settings import (
    DIGITALOCEAN_ENDPOINTS,
    PAGE_SIZE,
)


def _make_response(json_body: dict[str, Any] | None = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


class TestDigitalOceanPaginator:
    def test_advances_on_next_page_url(self) -> None:
        # DigitalOcean nests the next-page URL under links.pages.next; a page that has one must
        # continue pagination. A wrong json path (e.g. "links.next") would silently stop after page 1.
        p = _paginator()
        p.update_state(
            _make_response(
                {
                    "droplets": [{"id": 1}],
                    "links": {"pages": {"next": "https://api.digitalocean.com/v2/droplets?page=2"}},
                }
            )
        )

        assert p.has_next_page is True

        req = Request(method="GET", url="https://api.digitalocean.com/v2/droplets")
        p.update_request(req)
        assert req.url == "https://api.digitalocean.com/v2/droplets?page=2"

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(
                {"droplets": [{"id": 1}], "links": {"pages": {"last": "…", "prev": "…"}}}, id="last_page_no_next"
            ),
            pytest.param({"droplets": [{"id": 1}], "links": {}}, id="empty_links"),
            pytest.param({"droplets": []}, id="no_links_key"),
        ],
    )
    def test_stops_when_no_next_page(self, body: dict[str, Any]) -> None:
        p = _paginator()
        p.update_state(_make_response(body))
        assert p.has_next_page is False


class TestDigitalOceanGetResource:
    @pytest.mark.parametrize("endpoint", list(DIGITALOCEAN_ENDPOINTS.keys()))
    def test_resource_matches_endpoint_config(self, endpoint: str) -> None:
        config = DIGITALOCEAN_ENDPOINTS[endpoint]
        resource = get_resource(config)
        endpoint_def = _endpoint(resource)

        # data_selector must equal the JSON key DigitalOcean wraps the list under; a mismatch
        # yields an empty table without erroring, so this pins the contract per endpoint.
        assert endpoint_def["data_selector"] == config.data_selector
        assert endpoint_def["path"] == config.path
        assert endpoint_def["params"]["per_page"] == PAGE_SIZE
        # No incremental filter exists on any endpoint, so every table is full replace.
        assert resource["write_disposition"] == "replace"

    def test_images_limits_to_private(self) -> None:
        # Without private=true the images list also returns every public distribution/application
        # image — huge and identical for every account.
        resource = get_resource(DIGITALOCEAN_ENDPOINTS["images"])
        assert _endpoint(resource)["params"]["private"] == "true"


class TestDigitalOceanSensitiveFields:
    _DATABASE_RECORD = {
        "id": "db-1",
        "name": "prod-pg",
        "engine": "pg",
        "region": "nyc1",
        "connection": {"uri": "postgresql://doadmin:secret@host:25060/defaultdb", "password": "secret"},
        "private_connection": {"uri": "postgresql://doadmin:secret@priv-host:25060/defaultdb"},
        "standby_connection": {"password": "secret"},
        "standby_private_connection": {"password": "secret"},
        "users": [{"name": "doadmin", "password": "secret"}],
    }

    def test_databases_strips_credential_bearing_fields(self) -> None:
        # /v2/databases embeds live connection URIs, passwords, and the users list in every
        # record; without stripping they'd land in a queryable warehouse table.
        resource = digitalocean_source("dop_v1_token", "databases", team_id=1, job_id="job-1")
        [transformed] = resource._apply_transforms([dict(self._DATABASE_RECORD)])

        assert transformed == {"id": "db-1", "name": "prod-pg", "engine": "pg", "region": "nyc1"}

    def test_apps_strips_nested_env_and_log_credentials(self) -> None:
        # App specs bury env-var values and log-destination credentials inside spec.services and
        # the deployment spec copy; the strip must recurse to reach them while keeping metadata.
        record = {
            "id": "app-1",
            "spec": {
                "name": "web",
                "services": [
                    {
                        "name": "api",
                        "envs": [{"key": "SECRET_KEY", "value": "leak-me"}],
                        "log_destinations": [{"name": "dd", "datadog": {"api_key": "leak-me"}}],
                    }
                ],
            },
            "active_deployment": {"spec": {"services": [{"name": "api", "envs": [{"value": "leak-me"}]}]}},
        }
        resource = digitalocean_source("dop_v1_token", "apps", team_id=1, job_id="job-1")
        [transformed] = resource._apply_transforms([record])

        assert transformed == {
            "id": "app-1",
            "spec": {"name": "web", "services": [{"name": "api"}]},
            "active_deployment": {"spec": {"services": [{"name": "api"}]}},
        }

    def test_non_sensitive_endpoint_keeps_every_field(self) -> None:
        # Only endpoints that declare sensitive_fields get filtered; everything else must round-trip
        # untouched or the strip would silently drop real data.
        record = {"id": 1, "name": "web-1", "networks": {"v4": [{"ip_address": "1.2.3.4"}]}}
        resource = digitalocean_source("dop_v1_token", "droplets", team_id=1, job_id="job-1")

        assert resource._apply_transforms([dict(record)]) == [record]

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_databases_opts_out_of_sample_capture(self, mock_session: MagicMock) -> None:
        # Sample capture records the raw response before resource maps run, so the secrets would be
        # captured even though they're stripped from storage; the endpoint must disable capture.
        digitalocean_source("dop_v1_token", "databases", team_id=1, job_id="job-1")

        mock_session.assert_called_once_with(redact_values=("dop_v1_token",), capture=False)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_non_sensitive_endpoint_keeps_capture_on(self, mock_session: MagicMock) -> None:
        # Non-sensitive endpoints must not build their own session here, leaving the tracked client's
        # default (capture on) in place so their traffic stays in HTTP samples.
        digitalocean_source("dop_v1_token", "droplets", team_id=1, job_id="job-1")

        mock_session.assert_not_called()


class TestDigitalOceanValidateCredentials:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            pytest.param(200, True, id="ok"),
            pytest.param(401, False, id="unauthorized"),
            pytest.param(403, False, id="forbidden"),
            pytest.param(500, False, id="server_error"),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_maps_status_to_validity(self, mock_session: MagicMock, status_code: int, expected: bool) -> None:
        # The status code is returned alongside validity so the caller can tell an auth rejection
        # (401/403) apart from a transient failure (429/5xx) it must not report as an invalid token.
        mock_session.return_value.get.return_value = _make_response(status_code=status_code)
        assert validate_credentials("dop_v1_token") == (expected, status_code)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_transport_error_reports_no_status(self, mock_session: MagicMock) -> None:
        # A network failure must not surface as "token invalid"; it yields (False, None) so the
        # caller can distinguish it from a real auth rejection.
        mock_session.return_value.get.side_effect = ConnectionError("boom")
        assert validate_credentials("dop_v1_token") == (False, None)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_sends_bearer_token(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = _make_response(status_code=200)
        validate_credentials("dop_v1_token")

        _, kwargs = mock_session.return_value.get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer dop_v1_token"
