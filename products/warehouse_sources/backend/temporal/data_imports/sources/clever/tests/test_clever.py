import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.clever.clever import (
    CleverPaginator,
    CleverResumeConfig,
    clever_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clever.settings import (
    CLEVER_API_VERSION_V3_0,
    CLEVER_API_VERSION_V3_1,
    clever_base_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLEVER_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.clever.clever.make_tracked_session"
)
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


def _next_link(starting_after: str) -> dict[str, Any]:
    return {"rel": "next", "uri": f"/v3.0/districts?starting_after={starting_after}&limit=10000"}


class TestCleverPaginator:
    @pytest.mark.parametrize(
        "links",
        [
            [{"rel": "self", "uri": "/v3.0/districts"}],  # no `next` link at all
            [],  # empty links array
            [{"rel": "next", "uri": "/v3.0/districts?limit=10000"}],  # `next` link with no cursor value
        ],
    )
    def test_update_state_stops_when_no_resumable_next_link(self, links: list[dict[str, Any]]) -> None:
        paginator = CleverPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [{"data": {"id": "d1"}}], "links": links}
        paginator.update_state(response)
        assert paginator._starting_after is None
        assert paginator.has_next_page is False

    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = CleverPaginator()
        response = MagicMock()
        response.json.return_value = {"data": [], "links": []}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None


def _make_http_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestCleverSourceResumeBehavior:
    """End-to-end resume/incremental behaviour of ``clever_source`` via ``rest_api_resource``."""

    def _drive(
        self,
        endpoint: str,
        manager: MagicMock,
        responses: list[Response],
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
        api_version: str = CLEVER_API_VERSION_V3_1,
        sent_urls: list[str] | None = None,
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            if sent_urls is not None:
                sent_urls.append(request.url)
            return next(response_iter)

        with patch(CLIENT_SESSION_PATCH) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = clever_source(
                bearer_token="test-token",
                api_version=api_version,
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    @pytest.mark.parametrize("endpoint", ["Districts", "Schools", "Users", "Sections", "Courses", "Terms"])
    def test_fresh_full_refresh_run_saves_cursor_after_each_non_terminal_page(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"data": [{"data": {"id": "r1"}}], "links": [_next_link("r1")]}),
            _make_http_response({"data": [{"data": {"id": "r2"}}], "links": [_next_link("r2")]}),
            _make_http_response({"data": [{"data": {"id": "r3"}}], "links": []}),
        ]
        _, sent_params = self._drive(endpoint, manager, responses)

        starting_afters = [p.get("starting_after") for p in sent_params]
        assert starting_afters == [None, "r1", "r2"]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            CleverResumeConfig(starting_after="r1"),
            CleverResumeConfig(starting_after="r2"),
        ]

    @pytest.mark.parametrize(
        ("api_version", "expected_url"),
        [
            (CLEVER_API_VERSION_V3_0, "https://api.clever.com/v3.0/users"),
            (CLEVER_API_VERSION_V3_1, "https://api.clever.com/v3.1/users"),
        ],
    )
    def test_requests_target_the_pinned_api_version(self, api_version: str, expected_url: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"data": [{"data": {"id": "u1"}}], "links": [_next_link("u1")]}),
            _make_http_response({"data": [{"data": {"id": "u2"}}], "links": []}),
        ]
        sent_urls: list[str] = []
        self._drive("Users", manager, responses, api_version=api_version, sent_urls=sent_urls)

        assert sent_urls == [expected_url, expected_url]

    def test_resume_seeds_paginator_with_saved_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CleverResumeConfig(starting_after="cursor-resumed")

        responses = [_make_http_response({"data": [{"data": {"id": "r4"}}], "links": []})]
        _, sent_params = self._drive("Districts", manager, responses)

        assert sent_params[0]["starting_after"] == "cursor-resumed"
        manager.load_state.assert_called_once()

    def test_incremental_seeds_from_db_last_value_when_no_saved_state(self) -> None:
        """Events has no mid-run resume state (fresh run), but a prior sync's watermark
        should seed `starting_after` so the delta feed continues from where it left off."""
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"data": {"id": "evt-9"}}], "links": []})]
        _, sent_params = self._drive(
            "Events",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value="evt-5",
        )

        assert sent_params[0]["starting_after"] == "evt-5"

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"data": [{"data": {"id": "a"}}], "links": []})]
        self._drive("Districts", manager, responses)

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (500, False),
        ],
    )
    @patch(CLEVER_SESSION_PATCH)
    def test_validate_credentials_status_mapping(
        self, mock_session: MagicMock, status_code: int, expected_valid: bool
    ) -> None:
        mock_session.return_value.get.return_value = MagicMock(status_code=status_code)
        is_valid, message = validate_credentials("test-token", CLEVER_API_VERSION_V3_1)
        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    @patch(CLEVER_SESSION_PATCH)
    def test_validate_credentials_swallows_exceptions(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        is_valid, message = validate_credentials("test-token", CLEVER_API_VERSION_V3_1)
        assert is_valid is False
        assert message is not None

    @patch(CLEVER_SESSION_PATCH)
    def test_validate_credentials_redacts_token(self, mock_session: MagicMock) -> None:
        mock_session.return_value.get.return_value = MagicMock(status_code=200)
        validate_credentials("super-secret-token", CLEVER_API_VERSION_V3_1)
        mock_session.assert_called_once_with(redact_values=("super-secret-token",))

    @pytest.mark.parametrize(
        ("api_version", "expected_url"),
        [
            (CLEVER_API_VERSION_V3_0, "https://api.clever.com/v3.0/districts"),
            (CLEVER_API_VERSION_V3_1, "https://api.clever.com/v3.1/districts"),
        ],
    )
    @patch(CLEVER_SESSION_PATCH)
    def test_validate_credentials_probes_the_requested_api_version(
        self, mock_session: MagicMock, api_version: str, expected_url: str
    ) -> None:
        mock_session.return_value.get.return_value = MagicMock(status_code=200)
        validate_credentials("test-token", api_version)
        assert mock_session.return_value.get.call_args.args[0] == expected_url


def test_clever_base_url_rejects_unknown_version() -> None:
    # Falling back to another version would silently move a pinned source.
    with pytest.raises(ValueError):
        clever_base_url("v2.1")
