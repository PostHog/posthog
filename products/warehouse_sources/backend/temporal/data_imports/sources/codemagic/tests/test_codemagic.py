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
from products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.settings import (
    CODEMAGIC_V1,
    CODEMAGIC_V3,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class TestCodemagicBuildsPaginator:
    def test_init_request_injects_skip(self) -> None:
        paginator = CodemagicBuildsPaginator(skip=30)
        request = Request(method="GET", url="https://api.codemagic.io/builds")
        paginator.init_request(request)
        assert request.params["skip"] == 30

    def test_update_request_injects_current_skip(self) -> None:
        paginator = CodemagicBuildsPaginator()
        response = MagicMock()
        paginator.update_state(response, data=[{"_id": "b1"}])
        request = Request(method="GET", url="https://api.codemagic.io/builds")
        paginator.update_request(request)
        assert request.params["skip"] == 1


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestCodemagicSourceResumeBehavior:
    """End-to-end resume behaviour of the v1 ``codemagic_source`` via ``rest_api_resource``."""

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
                api_version=CODEMAGIC_V1,
            )
            list(cast(Iterable[Any], response.items()))
            return mock_session, sent_params

    def test_sync_client_does_not_follow_redirects(self) -> None:
        # The token rides in a custom header requests preserves across cross-origin redirects, so
        # the sync client must pin allow_redirects off. RESTClient forwards the client config's
        # value into every send().
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        send_kwargs: list[dict[str, Any]] = []
        response_iter = iter([_make_http_response({"applications": []})])

        def fake_send(request: Any, *_args: Any, **kwargs: Any) -> Response:
            send_kwargs.append(kwargs)
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
                endpoint="Applications",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
                api_version=CODEMAGIC_V1,
            )
            list(cast(Iterable[Any], response.items()))

        assert send_kwargs and all(kw.get("allow_redirects") is False for kw in send_kwargs)

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


class TestCodemagicV3Source:
    def _drive(
        self, endpoint: str, manager: MagicMock, responses: dict[str, list[Response]]
    ) -> tuple[Any, list[dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
        sent: list[tuple[str, dict[str, Any]]] = []
        queues = {path: iter(rs) for path, rs in responses.items()}

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent.append((request.url, dict(request.params or {})))
            return next(queues[request.url])

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
                api_version=CODEMAGIC_V3,
            )
            rows = [row for page in cast(Iterable[Any], response.items()) for row in page]
            return response, rows, sent

    def test_applications_page_through_user_apps(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        url = "https://codemagic.io/api/v3/user/apps"
        responses = {
            url: [
                _make_http_response({"data": [{"id": "a1"}], "page_size": 100, "current_page": 1, "total_pages": 2}),
                _make_http_response({"data": [{"id": "a2"}], "page_size": 100, "current_page": 2, "total_pages": 2}),
            ]
        }

        response, rows, sent = self._drive("Applications", manager, responses)

        assert [r["id"] for r in rows] == ["a1", "a2"]
        assert sent == [(url, {"page_size": 100, "page": 1}), (url, {"page_size": 100, "page": 2})]
        assert response.primary_keys == ["id"]
        assert response.partition_keys is None

    def test_builds_fan_out_over_teams_and_follow_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        teams_url = "https://codemagic.io/api/v3/user/teams"
        t1_url = "https://codemagic.io/api/v3/teams/t1/builds"
        t2_url = "https://codemagic.io/api/v3/teams/t2/builds"
        responses = {
            teams_url: [
                _make_http_response(
                    {"data": [{"id": "t1"}, {"id": "t2"}], "page_size": 100, "current_page": 1, "total_pages": 1}
                )
            ],
            t1_url: [
                _make_http_response({"data": [{"id": "b1"}], "page_size": 100, "cursor": "b1"}),
                _make_http_response({"data": [{"id": "b2"}], "page_size": 100, "cursor": None}),
            ],
            t2_url: [_make_http_response({"data": [{"id": "b3"}], "page_size": 100, "cursor": None})],
        }

        response, rows, sent = self._drive("Builds", manager, responses)

        assert [r["id"] for r in rows] == ["b1", "b2", "b3"]
        assert sent == [
            (teams_url, {"page_size": 100, "page": 1}),
            (t1_url, {"page_size": 100}),
            (t1_url, {"page_size": 100, "cursor": "b1"}),
            (t2_url, {"page_size": 100}),
        ]
        assert manager.save_state.call_args_list[0].args[0] == CodemagicResumeConfig(
            completed=[], current="/api/v3/teams/t1/builds", child_state={"cursor": "b1"}
        )
        assert response.primary_keys == ["id"]
        assert response.partition_keys == ["created_at"]

    def test_builds_resume_skips_completed_teams_and_seeds_cursor(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = CodemagicResumeConfig(
            completed=["/api/v3/teams/t1/builds"], current="/api/v3/teams/t2/builds", child_state={"cursor": "b9"}
        )
        teams_url = "https://codemagic.io/api/v3/user/teams"
        t2_url = "https://codemagic.io/api/v3/teams/t2/builds"
        responses = {
            teams_url: [
                _make_http_response(
                    {"data": [{"id": "t1"}, {"id": "t2"}], "page_size": 100, "current_page": 1, "total_pages": 1}
                )
            ],
            t2_url: [_make_http_response({"data": [{"id": "b10"}], "page_size": 100, "cursor": None})],
        }

        _, rows, sent = self._drive("Builds", manager, responses)

        assert [r["id"] for r in rows] == ["b10"]
        assert sent[1:] == [(t2_url, {"page_size": 100, "cursor": "b9"})]

    def test_unknown_version_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unsupported Codemagic API version"):
            codemagic_source(
                api_token="test-token",
                endpoint="Builds",
                team_id=123,
                job_id="test_job",
                resumable_source_manager=MagicMock(spec=ResumableSourceManager),
                api_version="v2",
            )


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

            is_valid, error = validate_credentials("test-token", CODEMAGIC_V3)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error == "Invalid Codemagic API token"

    @pytest.mark.parametrize(
        ("api_version", "expected_url"),
        [
            (CODEMAGIC_V1, "https://api.codemagic.io/apps"),
            (CODEMAGIC_V3, "https://codemagic.io/api/v3/user/apps"),
        ],
    )
    def test_validate_credentials_sends_auth_header_and_redacts_token(
        self, api_version: str, expected_url: str
    ) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codemagic.codemagic.make_tracked_session"
        ) as mock_make_session:
            mock_session = MagicMock()
            mock_session.get.return_value = MagicMock(status_code=200)
            mock_make_session.return_value = mock_session

            validate_credentials("secret-token", api_version)

        # allow_redirects=False keeps the custom-header token from following a 3xx off-host.
        mock_make_session.assert_called_once_with(redact_values=("secret-token",), allow_redirects=False)
        mock_session.get.assert_called_once_with(expected_url, headers={"x-auth-token": "secret-token"})
