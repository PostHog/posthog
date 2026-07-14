import json
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.digitalocean.digitalocean import (
    _paginator,
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
