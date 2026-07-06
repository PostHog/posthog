import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized

from products.messaging.backend.unlayer import UnlayerNotConfiguredError, UnlayerRenderError, render_design_html

DESIGN = {"schemaVersion": 16, "body": {"rows": []}}


def _response(status_code: int = 200, payload: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {}
    return response


class TestRenderDesignHtml:
    @override_settings(UNLAYER_API_KEY="test-key", UNLAYER_API_BASE_URL="https://api.unlayer.com")
    @patch("products.messaging.backend.unlayer.requests.post")
    def test_renders_html_from_design(self, mock_post):
        mock_post.return_value = _response(200, {"success": True, "data": {"html": "<html>ok</html>"}})

        assert render_design_html(DESIGN) == "<html>ok</html>"

        _, kwargs = mock_post.call_args
        assert mock_post.call_args[0][0] == "https://api.unlayer.com/v2/export/html"
        assert kwargs["auth"] == ("test-key", "")
        assert kwargs["json"] == {"displayMode": "email", "design": DESIGN}

    @override_settings(UNLAYER_API_KEY="")
    def test_raises_when_api_key_missing(self):
        with pytest.raises(UnlayerNotConfiguredError):
            render_design_html(DESIGN)

    @parameterized.expand(
        [
            ("http_error", _response(500, {"error": "boom"}), None),
            ("missing_html", _response(200, {"success": True, "data": {}}), None),
            ("network_error", None, requests.ConnectionError("refused")),
        ]
    )
    @override_settings(UNLAYER_API_KEY="test-key")
    @patch("products.messaging.backend.unlayer.requests.post")
    def test_raises_render_error(self, _name, response, side_effect, mock_post):
        if side_effect is not None:
            mock_post.side_effect = side_effect
        else:
            mock_post.return_value = response

        with pytest.raises(UnlayerRenderError):
            render_design_html(DESIGN)
