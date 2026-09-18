import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.bluesky import (
    BlueskyResumeConfig,
    bluesky_source,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestGetResource:
    @pytest.mark.parametrize(
        ("name", "expected_path", "expected_selector"),
        [
            ("Profile", "/xrpc/app.bsky.actor.getProfile", "$"),
            ("Posts", "/xrpc/app.bsky.feed.getAuthorFeed", "feed[*].post"),
            ("Followers", "/xrpc/app.bsky.graph.getFollowers", "followers"),
            ("Follows", "/xrpc/app.bsky.graph.getFollows", "follows"),
        ],
    )
    def test_endpoint_shape(self, name: str, expected_path: str, expected_selector: str) -> None:
        resource = get_resource(name, actor="jay.bsky.team")
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)

        assert endpoint["path"] == expected_path
        assert endpoint["data_selector"] == expected_selector

        params = endpoint["params"]
        assert isinstance(params, dict)
        assert params["actor"] == "jay.bsky.team"

    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(KeyError):
            get_resource("Nope", actor="jay.bsky.team")

    def test_posts_excludes_replies(self) -> None:
        # Matches what most marketing/brand tracking cares about: the author's own content.
        resource = get_resource("Posts", actor="jay.bsky.team")
        endpoint = resource["endpoint"]
        assert isinstance(endpoint, dict)
        params = endpoint["params"]
        assert isinstance(params, dict)
        assert params["filter"] == "posts_no_replies"


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestValidateCredentials:
    _MAKE_SESSION = (
        "products.warehouse_sources.backend.temporal.data_imports.sources.bluesky.bluesky.make_tracked_session"
    )

    @patch(_MAKE_SESSION)
    def test_valid_actor(self, mock_make_session: MagicMock) -> None:
        mock_session = mock_make_session.return_value
        mock_session.get.return_value = _make_http_response({"did": "did:plc:abc"}, 200)

        is_valid, message = validate_credentials("jay.bsky.team")

        assert (is_valid, message) == (True, None)
        mock_session.get.assert_called_once_with(
            "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
            params={"actor": "jay.bsky.team"},
        )

    @patch(_MAKE_SESSION)
    def test_missing_actor_surfaces_api_message(self, mock_make_session: MagicMock) -> None:
        mock_session = mock_make_session.return_value
        mock_session.get.return_value = _make_http_response(
            {"error": "InvalidRequest", "message": "Profile not found"}, 400
        )

        is_valid, message = validate_credentials("missing.bsky.social")

        assert is_valid is False
        assert message == "Profile not found"

    @patch(_MAKE_SESSION)
    def test_missing_actor_without_api_message_falls_back(self, mock_make_session: MagicMock) -> None:
        mock_session = mock_make_session.return_value
        mock_session.get.return_value = _make_http_response({}, 400)

        is_valid, message = validate_credentials("missing.bsky.social")

        assert is_valid is False
        assert message == "That handle or DID couldn't be found on Bluesky. Check the spelling and try again."

    @patch(_MAKE_SESSION)
    def test_non_json_error_body_falls_back(self, mock_make_session: MagicMock) -> None:
        mock_session = mock_make_session.return_value
        resp = Response()
        resp.status_code = 400
        resp._content = b"<html>not json</html>"
        mock_session.get.return_value = resp

        is_valid, message = validate_credentials("missing.bsky.social")

        assert is_valid is False
        assert message == "That handle or DID couldn't be found on Bluesky. Check the spelling and try again."

    @patch(_MAKE_SESSION)
    def test_unexpected_status_falls_back_to_generic_message(self, mock_make_session: MagicMock) -> None:
        mock_session = mock_make_session.return_value
        mock_session.get.return_value = _make_http_response({}, 503)

        is_valid, message = validate_credentials("jay.bsky.team")

        assert is_valid is False
        assert message == "Bluesky returned an unexpected error (503)."


class TestBlueskySourceResumeBehavior:
    """End-to-end resume behaviour of ``bluesky_source`` via ``rest_api_resource``."""

    _MAKE_SESSION = (
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"
        ".make_tracked_session"
    )

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        """Drive ``bluesky_source`` with a mocked HTTP session.

        Returns ``(mock_session, sent_params)`` where ``sent_params`` is a list of shallow copies
        of ``request.params`` captured at send-time, since the underlying ``Request`` is mutated
        in-place by the paginator between pages.
        """
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(self._MAKE_SESSION) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = bluesky_source(
                actor="jay.bsky.team",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    @pytest.mark.parametrize(
        ("endpoint", "list_key", "item"),
        [
            ("Posts", "feed", {"post": {"uri": "at://x"}}),
            ("Followers", "followers", {"did": "did:plc:1"}),
            ("Follows", "follows", {"did": "did:plc:1"}),
        ],
    )
    def test_fresh_run_saves_cursor_after_each_non_terminal_page(
        self, endpoint: str, list_key: str, item: dict[str, Any]
    ) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({list_key: [item], "cursor": "cursor-1"}),
            _make_http_response({list_key: [item], "cursor": "cursor-2"}),
            _make_http_response({list_key: [item]}),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        cursors_sent = [p.get("cursor") for p in sent_params]
        assert cursors_sent == [None, "cursor-1", "cursor-2"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            BlueskyResumeConfig(cursor="cursor-1"),
            BlueskyResumeConfig(cursor="cursor-2"),
        ]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BlueskyResumeConfig(cursor="cursor-resumed")

        responses = [_make_http_response({"followers": [{"did": "did:plc:1"}]})]
        _, sent_params = self._drive("Followers", manager, responses)

        assert [p.get("cursor") for p in sent_params] == ["cursor-resumed"]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"followers": [{"did": "did:plc:1"}]})]
        self._drive("Followers", manager, responses)

        manager.save_state.assert_not_called()

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"followers": [{"did": "did:plc:1"}]})]
        self._drive("Followers", manager, responses)

        manager.load_state.assert_not_called()

    def test_profile_endpoint_is_a_single_page_and_never_saves_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"did": "did:plc:1", "handle": "jay.bsky.team"})]
        _, sent_params = self._drive("Profile", manager, responses)

        assert len(sent_params) == 1
        manager.save_state.assert_not_called()

    def test_posts_yields_flattened_post_objects(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"feed": [{"post": {"uri": "at://x", "indexedAt": "2026-01-01T00:00:00Z"}}]})]
        with patch(self._MAKE_SESSION) as mock_make_session:
            mock_session = mock_make_session.return_value
            mock_session.headers = {}
            response_iter = iter(responses)
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = lambda *args, **kwargs: next(response_iter)

            resource = bluesky_source(
                actor="jay.bsky.team",
                endpoint="Posts",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            pages = list(cast(Iterable[Any], resource))

        assert pages == [[{"uri": "at://x", "indexedAt": "2026-01-01T00:00:00Z"}]]
