import json
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean import (
    digitalocean_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.settings import (
    DIGITALOCEAN_ENDPOINTS,
)


def _make_response(json_body: dict[str, Any] | None = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body or {}).encode()
    return resp


def _endpoint(resource: Any) -> dict[str, Any]:
    return cast(dict[str, Any], resource["endpoint"])


class TestDigitalOceanGetResource:
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

    @pytest.mark.parametrize(
        "endpoint,capture_disabled",
        [
            pytest.param("databases", True, id="secrets_in_the_response"),
            pytest.param("invoice_summaries", True, id="billing_identity_in_the_response"),
            pytest.param("invoice_items", True, id="resource_level_spend_in_the_response"),
            pytest.param("database_backups", True, id="secrets_in_the_fanout_parent_response"),
            pytest.param("database_events", True, id="secrets_in_the_other_fanout_parent_response"),
            pytest.param("droplets", False, id="nothing_to_withhold"),
        ],
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean.make_tracked_session"
    )
    def test_capture_is_disabled_only_where_the_response_must_not_be_sampled(
        self, mock_session: MagicMock, endpoint: str, capture_disabled: bool
    ) -> None:
        # Sample capture records the raw response before resource maps run, so stripping a field
        # from storage does not keep it out of a sample. An endpoint holding secrets or billing
        # identity must build its own capture-off session; every other endpoint must not, leaving
        # the tracked client's default (capture on) in place.
        digitalocean_source("dop_v1_token", endpoint, team_id=1, job_id="job-1")

        if capture_disabled:
            mock_session.assert_called_once_with(redact_values=("dop_v1_token",), capture=False)
        else:
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
