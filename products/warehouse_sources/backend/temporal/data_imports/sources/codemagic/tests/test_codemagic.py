import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.codemagic import (
    CodemagicBuildsPaginator,
    CodemagicResumeConfig,
    codemagic_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestCodemagicBuildsPaginator:
    def test_initial_state(self) -> None:
        paginator = CodemagicBuildsPaginator()
        assert paginator._skip == 0
        assert paginator.has_next_page is True

    def test_init_request_injects_skip(self) -> None:
        paginator = CodemagicBuildsPaginator(skip=30)
        request = Request(method="GET", url="https://api.codemagic.io/builds")
        paginator.init_request(request)
        assert request.params["skip"] == 30

    @pytest.mark.parametrize(
        ("page_data", "expected_skip", "expected_has_next"),
        [
            ([{"_id": "b1"}, {"_id": "b2"}], 2, True),
            ([{"_id": "b1"}], 1, True),
            ([], 0, False),
            (None, 0, False),
        ],
    )
    def test_update_state_advances_skip_by_actual_page_length(
        self, page_data: list[dict[str, Any]] | None, expected_skip: int, expected_has_next: bool
    ) -> None:
        # No documented page-size param means skip must advance by whatever the server
        # actually returned, not a declared limit.
        paginator = CodemagicBuildsPaginator()
        response = MagicMock()
        paginator.update_state(response, data=page_data)
        assert paginator._skip == expected_skip
        assert paginator.has_next_page is expected_has_next

    def test_update_state_accumulates_across_pages(self) -> None:
        paginator = CodemagicBuildsPaginator()
        response = MagicMock()
        paginator.update_state(response, data=[{"_id": "b1"}, {"_id": "b2"}])
        paginator.update_state(response, data=[{"_id": "b3"}])
        assert paginator._skip == 3
        assert paginator.has_next_page is True

    def test_update_request_injects_current_skip(self) -> None:
        paginator = CodemagicBuildsPaginator()
        response = MagicMock()
        paginator.update_state(response, data=[{"_id": "b1"}])
        request = Request(method="GET", url="https://api.codemagic.io/builds")
        paginator.update_request(request)
        assert request.params["skip"] == 1

    def test_get_resume_state_returns_none_when_terminal(self) -> None:
        paginator = CodemagicBuildsPaginator()
        response = MagicMock()
        paginator.update_state(response, data=[])
        assert paginator.get_resume_state() is None

    def test_get_resume_state_returns_skip_when_more_pages(self) -> None:
        paginator = CodemagicBuildsPaginator()
        response = MagicMock()
        paginator.update_state(response, data=[{"_id": "b1"}])
        assert paginator.get_resume_state() == {"skip": 1}

    @pytest.mark.parametrize(
        ("label", "seeded_skip"),
        [
            ("fresh", None),
            ("resumed", 42),
        ],
    )
    def test_set_resume_state_seeds_subsequent_requests(self, label: str, seeded_skip: int | None) -> None:
        paginator = CodemagicBuildsPaginator()
        if seeded_skip is not None:
            paginator.set_resume_state({"skip": seeded_skip})

        request = Request(method="GET", url="https://api.codemagic.io/builds")
        paginator.init_request(request)

        expected = seeded_skip if seeded_skip is not None else 0
        assert request.params["skip"] == expected

    def test_set_resume_state_ignores_missing_skip(self) -> None:
        paginator = CodemagicBuildsPaginator()
        paginator.set_resume_state({})
        assert paginator._skip == 0


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestCodemagicSourceResumeBehavior:
    """End-to-end resume behaviour of ``codemagic_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: MagicMock, responses: list[Response]
    ) -> tuple[MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            response = codemagic_source(
                api_token="test-token",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], response.items()))
            return mock_session, sent_params

    def test_applications_endpoint_is_a_single_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"applications": [{"_id": "app1", "appName": "My App"}]})]
        _, sent_params = self._drive("Applications", manager, responses)

        assert len(sent_params) == 1
        manager.save_state.assert_not_called()

    def test_builds_fresh_run_saves_skip_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"builds": [{"_id": "b1"}, {"_id": "b2"}]}),
            _make_http_response({"builds": [{"_id": "b3"}]}),
            _make_http_response({"builds": []}),
        ]
        _, sent_params = self._drive("Builds", manager, responses)

        skips_sent = [p.get("skip") for p in sent_params]
        assert skips_sent == [0, 2, 3]

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            CodemagicResumeConfig(skip=2),
            CodemagicResumeConfig(skip=3),
        ]

    def test_builds_resume_seeds_paginator_with_saved_skip(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CodemagicResumeConfig(skip=60)

        responses = [_make_http_response({"builds": []})]
        _, sent_params = self._drive("Builds", manager, responses)

        assert sent_params[0]["skip"] == 60
        manager.load_state.assert_called_once()

    def test_builds_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [_make_http_response({"builds": []})]
        self._drive("Builds", manager, responses)

        manager.save_state.assert_not_called()

    def test_applications_does_not_load_resume_state(self) -> None:
        # Applications is a single unpaginated page — resume plumbing only applies to Builds.
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CodemagicResumeConfig(skip=999)

        responses = [_make_http_response({"applications": []})]
        self._drive("Applications", manager, responses)

        manager.load_state.assert_not_called()

    @pytest.mark.parametrize(
        ("endpoint", "expected_sort_mode"),
        [
            ("Applications", "asc"),
            ("Builds", "desc"),
        ],
    )
    def test_sort_mode_reflects_actual_response_ordering(self, endpoint: str, expected_sort_mode: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        wrapper_key = "applications" if endpoint == "Applications" else "builds"

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = lambda *_a, **_k: _make_http_response({wrapper_key: []})

            response = codemagic_source(
                api_token="test-token",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )

        assert response.sort_mode == expected_sort_mode
        assert response.primary_keys == ["_id"]

    def test_builds_partitions_on_created_at(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = lambda *_a, **_k: _make_http_response({"builds": []})

            response = codemagic_source(
                api_token="test-token",
                endpoint="Builds",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )

        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    def test_applications_has_no_partitioning(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = lambda *_a, **_k: _make_http_response({"applications": []})

            response = codemagic_source(
                api_token="test-token",
                endpoint="Applications",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )

        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected_valid"),
        [
            (200, True),
            (401, False),
            (403, False),
        ],
    )
    def test_validate_credentials_maps_status_code(self, status_code: int, expected_valid: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.codemagic.make_tracked_session"
        ) as mock_make_session:
            mock_session = MagicMock()
            mock_session.get.return_value = MagicMock(status_code=status_code)
            mock_make_session.return_value = mock_session

            is_valid, error = validate_credentials("test-token")

        assert is_valid is expected_valid
        if not expected_valid:
            assert error == "Invalid Codemagic API token"

    def test_validate_credentials_sends_auth_header_and_redacts_token(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.codemagic.make_tracked_session"
        ) as mock_make_session:
            mock_session = MagicMock()
            mock_session.get.return_value = MagicMock(status_code=200)
            mock_make_session.return_value = mock_session

            validate_credentials("secret-token")

        mock_make_session.assert_called_once_with(redact_values=("secret-token",))
        mock_session.get.assert_called_once_with(
            "https://api.codemagic.io/apps", headers={"x-auth-token": "secret-token"}
        )
