from unittest.mock import patch

from django.test import SimpleTestCase

import requests
from parameterized import parameterized

from products.mcp_store.backend.icons import composio_logo_http_response, is_valid_toolkit_slug


def _response(
    status_code: int = 200, content_type: str = "image/svg+xml", body: bytes = b"<svg/>"
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers["content-type"] = content_type
    response._content = body
    return response


class TestComposioLogoProxy(SimpleTestCase):
    @parameterized.expand(
        [
            ("traversal", "../../secret"),
            ("absolute", "/etc/passwd"),
            ("host_switch", "evil.com/x"),
            ("query", "gmail?x=1"),
            ("uppercase", "Gmail"),
            ("hyphen", "google-sheets"),
            ("empty", ""),
            ("too_long", "a" * 65),
        ]
    )
    def test_slug_that_could_escape_the_logo_path_is_rejected(self, _name: str, slug: str) -> None:
        # The slug is interpolated into an outbound URL, so this is the boundary between a caller
        # controlled string and a path on someone else's host.
        assert not is_valid_toolkit_slug(slug)
        with patch("products.mcp_store.backend.icons.composio_logo_request") as request:
            assert composio_logo_http_response(slug, team_id=1).status_code == 404
        assert not request.called

    @parameterized.expand([("plain", "gmail"), ("underscore", "capsule_crm"), ("digits", "wakatime2")])
    def test_valid_slug_is_proxied(self, _name: str, slug: str) -> None:
        with patch("products.mcp_store.backend.icons.composio_logo_request", return_value=_response()):
            response = composio_logo_http_response(slug, team_id=1)
        assert response.status_code == 200
        assert response["Content-Security-Policy"].startswith("sandbox")
        assert response["X-Content-Type-Options"] == "nosniff"

    @parameterized.expand(
        [
            ("html", "text/html"),
            ("script", "application/javascript"),
            ("json", "application/json"),
        ]
    )
    def test_non_image_upstream_body_is_not_served_from_our_origin(self, _name: str, content_type: str) -> None:
        with patch(
            "products.mcp_store.backend.icons.composio_logo_request",
            return_value=_response(content_type=content_type, body=b"<script>alert(1)</script>"),
        ):
            assert composio_logo_http_response("gmail", team_id=1).status_code == 404

    def test_upstream_failure_falls_back_to_the_generic_glyph(self) -> None:
        with patch(
            "products.mcp_store.backend.icons.composio_logo_request",
            side_effect=requests.ConnectionError("down"),
        ):
            assert composio_logo_http_response("gmail", team_id=1).status_code == 404
