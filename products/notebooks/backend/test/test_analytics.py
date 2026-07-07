from typing import cast

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.request import Request

from posthog.auth import SessionAuthentication

from products.notebooks.backend.analytics import (
    NOTEBOOK_CREATED_EVENT,
    NotebookCreationSource,
    capture_notebook_created,
    notebook_node_count,
)
from products.notebooks.backend.presentation.views.notebook import classify_request_source


class _FakeKeyAuth:
    pass


class _FakeRequest:
    def __init__(self, authenticator, mcp_consumer=None, mcp_oauth_client=None):
        self.successful_authenticator = authenticator
        self.META = {}
        if mcp_consumer is not None:
            self.META["HTTP_X_POSTHOG_MCP_CONSUMER"] = mcp_consumer
        if mcp_oauth_client is not None:
            self.META["HTTP_X_POSTHOG_MCP_OAUTH_CLIENT_NAME"] = mcp_oauth_client


def _fake_request(authenticator, mcp_consumer=None, mcp_oauth_client=None) -> Request:
    return cast(Request, _FakeRequest(authenticator, mcp_consumer, mcp_oauth_client))


class TestNotebookAnalytics(BaseTest):
    @parameterized.expand(
        [
            ("two_nodes", {"type": "doc", "content": [{}, {}]}, 2),
            ("empty_doc", {"type": "doc", "content": []}, 0),
            ("no_content_key", {"type": "doc"}, 0),
            ("none", None, None),
            ("not_a_dict", "just text", None),
        ]
    )
    def test_notebook_node_count(self, _name, content, expected):
        self.assertEqual(notebook_node_count(content), expected)

    def test_classify_request_source_session_is_ui(self):
        source, extra = classify_request_source(_fake_request(SessionAuthentication()))
        self.assertEqual(source, NotebookCreationSource.UI)
        self.assertEqual(extra, {})

    def test_classify_request_source_api_key_captures_mcp_client_identity(self):
        # The MCP server forwards mcp_consumer (posthog-code -> PostHog Code) and mcp_oauth_client
        # (the OAuth app, e.g. Claude), which is how Q4 (PostHog Code) is split from Q5.
        source, extra = classify_request_source(
            _fake_request(_FakeKeyAuth(), mcp_consumer="posthog-code", mcp_oauth_client="Claude")
        )
        self.assertEqual(source, NotebookCreationSource.MCP)
        self.assertEqual(
            extra,
            {"api_key_type": "_FakeKeyAuth", "mcp_consumer": "posthog-code", "mcp_oauth_client": "Claude"},
        )

    def test_classify_request_source_no_authenticator_defaults_to_ui(self):
        source, extra = classify_request_source(_fake_request(None))
        self.assertEqual(source, (NotebookCreationSource.UI))
        self.assertEqual(extra, {})

    @patch("products.notebooks.backend.analytics.report_user_action")
    def test_request_path_captures_via_report_user_action_and_drops_none_props(self, mock_report):
        capture_notebook_created(
            short_id="abc123",
            creation_source=NotebookCreationSource.UI,
            team_id=self.team.id,
            user=self.user,
            request=_fake_request(SessionAuthentication()),
            visibility="private",
            node_count=3,
            mcp_consumer=None,
            api_key_type=None,
        )
        self.assertEqual(mock_report.call_count, 1)
        args, kwargs = mock_report.call_args
        self.assertEqual(args[0], self.user)
        self.assertEqual(args[1], NOTEBOOK_CREATED_EVENT)
        # None-valued optional props are dropped so they don't clutter the event.
        self.assertEqual(
            args[2],
            {"short_id": "abc123", "creation_source": "ui", "visibility": "private", "node_count": 3},
        )
