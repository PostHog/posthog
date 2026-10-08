import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized

from products.messaging.backend.unlayer import (
    UnlayerNotConfiguredError,
    UnlayerRenderError,
    expand_custom_tools,
    render_design_html,
)

DESIGN = {"schemaVersion": 16, "body": {"rows": []}}


def _design_with_custom_block(slug: str = "unsubscribe_link") -> dict:
    return {
        "schemaVersion": 16,
        "body": {
            "rows": [
                {
                    "id": "row1",
                    "columns": [
                        {
                            "id": "col1",
                            "contents": [
                                {
                                    "id": "custom1",
                                    "slug": slug,
                                    "type": "custom",
                                    "values": {
                                        "containerPadding": "10px",
                                        "unsubscribe_link_content": '<a href="{{ unsubscribe_url }}">Unsubscribe</a>',
                                        "_meta": {"htmlID": "u_content_custom_unsubscribe_link_1"},
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


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


class TestExpandCustomTools:
    def test_expands_unsubscribe_block_into_html_block(self):
        content = expand_custom_tools(_design_with_custom_block())["body"]["rows"][0]["columns"][0]["contents"][0]

        assert content["type"] == "html"
        assert content["values"]["html"] == '<a href="{{ unsubscribe_url }}">Unsubscribe</a>'
        assert content["id"] == "custom1"
        assert content["values"]["containerPadding"] == "10px"

    def test_leaves_the_stored_design_untouched(self):
        design = _design_with_custom_block()

        expand_custom_tools(design)

        assert design["body"]["rows"][0]["columns"][0]["contents"][0]["type"] == "custom"

    def test_leaves_unknown_custom_tools_alone(self):
        design = _design_with_custom_block(slug="hologram")

        content = expand_custom_tools(design)["body"]["rows"][0]["columns"][0]["contents"][0]

        assert content["type"] == "custom"
        assert "html" not in content["values"]

    @parameterized.expand(
        [
            ("body_not_an_object", {"body": "nope"}),
            ("rows_not_a_list", {"body": {"rows": "nope"}}),
            ("row_not_an_object", {"body": {"rows": ["nope"]}}),
        ]
    )
    def test_tolerates_a_malformed_design(self, _name, design):
        assert expand_custom_tools(design) == design

    @override_settings(UNLAYER_API_KEY="test-key", UNLAYER_API_BASE_URL="https://api.unlayer.com")
    @patch("products.messaging.backend.unlayer.requests.post")
    def test_export_is_sent_the_expanded_design(self, mock_post):
        mock_post.return_value = _response(200, {"success": True, "data": {"html": "<html>ok</html>"}})

        render_design_html(_design_with_custom_block())

        _, kwargs = mock_post.call_args
        exported = kwargs["json"]["design"]["body"]["rows"][0]["columns"][0]["contents"][0]
        assert exported["type"] == "html"
