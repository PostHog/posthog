import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter.settings import TWITTER_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.twitter.twitter import (
    TwitterResumeConfig,
    TwitterUserNotFoundError,
    endpoint_permissions,
    normalize_username,
    resolve_user_id,
    to_rfc3339,
    twitter_source,
    validate_credentials,
)

_SESSION_TARGET = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
_DIRECT_SESSION_TARGET = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.twitter.twitter.make_tracked_session"
)


def _json_response(body: dict[str, Any], status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _pages(response: SourceResponse) -> list[list[dict[str, Any]]]:
    # SourceResponse.items is typed for async sources too; every X endpoint is synchronous.
    return list(cast(Iterable[list[dict[str, Any]]], response.items()))


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


class TestNormalizeUsername:
    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "@",
            "a" * 16,
            "post hog",
            "post-hog",
            # A pasted profile URL would otherwise be interpolated straight into the request path.
            "https://x.com/posthog",
            "posthog/../../2/users/me",
        ],
    )
    def test_rejects_anything_else(self, raw: str) -> None:
        with pytest.raises(ValueError):
            normalize_username(raw)


class TestToRfc3339:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (datetime(2024, 3, 1, 12, 30, 45, tzinfo=UTC), "2024-03-01T12:30:45Z"),
            # A naive watermark is read as UTC rather than the worker's local zone.
            (datetime(2024, 3, 1, 12, 30, 45), "2024-03-01T12:30:45Z"),
            # Microseconds are dropped: X takes second granularity only.
            (datetime(2024, 3, 1, 12, 30, 45, 987654, tzinfo=UTC), "2024-03-01T12:30:45Z"),
            # The endpoint's `initial_value` arrives as a string on the first incremental run.
            ("2010-11-06T00:00:00Z", "2010-11-06T00:00:00Z"),
            ("2024-03-01T12:30:45+00:00", "2024-03-01T12:30:45Z"),
        ],
    )
    def test_formats_a_watermark(self, value: Any, expected: str) -> None:
        assert to_rfc3339(value) == expected


class TestResolveUserId:
    def test_raises_when_the_handle_has_no_account(self) -> None:
        with patch(_DIRECT_SESSION_TARGET) as MockSession:
            MockSession.return_value.get.return_value = _json_response(
                {"errors": [{"title": "Not Found Error", "detail": "Could not find user"}]}
            )
            with pytest.raises(TwitterUserNotFoundError):
                resolve_user_id("token", "posthog")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "body", "expected_ok", "expected_fragment"),
        [
            (200, {"data": {"id": "1"}}, True, None),
            (401, {"title": "Unauthorized"}, False, "rejected that bearer token"),
            (403, {"title": "Forbidden"}, False, "API credits"),
            (500, {}, False, "HTTP 500"),
            # X answers an unknown handle with 200 and an `errors` array, not a 404.
            (200, {"errors": [{"title": "Not Found Error"}]}, False, "no account with the handle"),
        ],
    )
    def test_maps_each_response_to_a_message(
        self, status_code: int, body: dict[str, Any], expected_ok: bool, expected_fragment: str | None
    ) -> None:
        with patch(_DIRECT_SESSION_TARGET) as MockSession:
            MockSession.return_value.get.return_value = _json_response(body, status_code=status_code)
            ok, message = validate_credentials("token", "posthog")

        assert ok is expected_ok
        if expected_fragment is None:
            assert message is None
        else:
            assert message is not None and expected_fragment in message

    def test_rejects_a_malformed_handle_without_calling_the_api(self) -> None:
        with patch(_DIRECT_SESSION_TARGET) as MockSession:
            ok, message = validate_credentials("token", "https://x.com/posthog")

        assert ok is False
        assert message is not None and "handle" in message
        MockSession.return_value.get.assert_not_called()


class TestEndpointPermissions:
    def test_reports_the_tables_the_app_cannot_read(self) -> None:
        responses = {
            "/2/users/by/username/posthog": _json_response({"data": {"id": "7"}}),
            "/2/users/by": _json_response({"data": [{"id": "7"}]}),
            "/2/users/7/tweets": _json_response({"data": []}),
            "/2/users/7/followers": _json_response({"title": "Forbidden"}, status_code=403),
        }

        def fake_get(url: str, **_kwargs: Any) -> Response:
            return responses[urlsplit(url).path]

        with patch(_DIRECT_SESSION_TARGET) as MockSession:
            MockSession.return_value.get.side_effect = fake_get
            result = endpoint_permissions("token", "posthog", ["Profile", "Posts", "Followers"])

        assert result["Profile"] is None
        assert result["Posts"] is None
        assert result["Followers"] is not None and "API access" in result["Followers"]

    def test_reports_nothing_when_the_handle_will_not_resolve(self) -> None:
        with patch(_DIRECT_SESSION_TARGET) as MockSession:
            MockSession.return_value.get.return_value = _json_response({"errors": [{"title": "Not Found Error"}]})
            assert endpoint_permissions("token", "posthog", ["Posts"]) == {}

    def test_treats_a_network_failure_as_reachable(self) -> None:
        def fake_get(url: str, **_kwargs: Any) -> Response:
            if urlsplit(url).path.endswith("/username/posthog"):
                return _json_response({"data": {"id": "7"}})
            raise OSError("connection reset")

        with patch(_DIRECT_SESSION_TARGET) as MockSession:
            MockSession.return_value.get.side_effect = fake_get
            assert endpoint_permissions("token", "posthog", ["Posts"]) == {"Posts": None}


class TestTwitterSourceRequests:
    """Request shaping, pagination and resume, driven through ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        responses: list[Response],
        *,
        manager: MagicMock | None = None,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[str], list[list[dict[str, Any]]], MagicMock]:
        if manager is None:
            manager = MagicMock(spec=ResumableSourceManager)
            manager.can_resume.return_value = False

        sent_urls: list[str] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_urls.append(request.url)
            return next(response_iter)

        with (
            patch(_DIRECT_SESSION_TARGET) as MockLookupSession,
            patch(_SESSION_TARGET) as MockSession,
        ):
            MockLookupSession.return_value.get.return_value = _json_response({"data": {"id": "7"}})
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req.prepare()
            mock_session.send.side_effect = fake_send

            response = twitter_source(
                bearer_token="token",
                username="posthog",
                endpoint=endpoint,
                team_id=1,
                job_id="job",
                resumable_source_manager=manager,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
            )
            return sent_urls, _pages(response), manager

    def test_first_incremental_run_falls_back_to_the_api_floor(self) -> None:
        sent_urls, _, _ = self._drive(
            "Posts",
            [_json_response({"data": [{"id": "1"}], "meta": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
        )

        assert _query(sent_urls[0])["start_time"] == ["2010-11-06T00:00:00Z"]

    @pytest.mark.parametrize("endpoint", ["LikedPosts", "Followers", "Following", "OwnedLists"])
    def test_endpoints_without_a_time_filter_never_send_one(self, endpoint: str) -> None:
        sent_urls, _, _ = self._drive(
            endpoint,
            [_json_response({"data": [{"id": "1"}], "meta": {}})],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
        )

        assert "start_time" not in _query(sent_urls[0])

    def test_profile_queries_the_handle_without_resolving_an_id(self) -> None:
        sent_urls, pages, _ = self._drive("Profile", [_json_response({"data": [{"id": "7", "username": "posthog"}]})])

        assert urlsplit(sent_urls[0]).path == "/2/users/by"
        assert _query(sent_urls[0])["usernames"] == ["posthog"]
        assert pages == [[{"id": "7", "username": "posthog"}]]

    def test_follows_the_next_token_and_saves_it_after_each_page(self) -> None:
        sent_urls, pages, manager = self._drive(
            "Posts",
            [
                _json_response({"data": [{"id": "1"}], "meta": {"next_token": "page2"}}),
                _json_response({"data": [{"id": "2"}], "meta": {}}),
            ],
        )

        assert "pagination_token" not in _query(sent_urls[0])
        assert _query(sent_urls[1])["pagination_token"] == ["page2"]
        assert [row["id"] for page in pages for row in page] == ["1", "2"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [TwitterResumeConfig(pagination_token="page2")]

    def test_resume_seeds_the_saved_pagination_token(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = TwitterResumeConfig(pagination_token="saved")

        sent_urls, _, _ = self._drive("Posts", [_json_response({"data": [{"id": "9"}], "meta": {}})], manager=manager)

        assert _query(sent_urls[0])["pagination_token"] == ["saved"]

    def test_does_not_load_state_when_it_cannot_resume(self) -> None:
        _, _, manager = self._drive("Posts", [_json_response({"data": [{"id": "1"}], "meta": {}})])

        manager.load_state.assert_not_called()


class TestTwitterSourceResponse:
    def test_an_unknown_endpoint_raises_the_retryable_error(self) -> None:
        with pytest.raises(UnknownResourceError):
            twitter_source(
                bearer_token="token",
                username="posthog",
                endpoint="NotAnEndpoint",
                team_id=1,
                job_id="job",
                resumable_source_manager=MagicMock(spec=ResumableSourceManager),
                db_incremental_field_last_value=None,
            )

    def test_every_endpoint_path_resolves_to_a_single_placeholder(self) -> None:
        # A stray placeholder would reach X verbatim and 404 the whole table.
        for config in TWITTER_ENDPOINTS.values():
            formatted = config.path.format(user_id="7") if config.needs_user_id else config.path
            assert "{" not in formatted
