import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.waydev.waydev import (
    WaydevResumeConfig,
    get_resource,
    validate_credentials,
    waydev_source,
)

# validate_credentials builds its own tracked session in the waydev module.
WAYDEV_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.waydev.waydev.make_tracked_session"
)


def _make_http_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


class TestGetResource:
    def test_unknown_endpoint_raises(self) -> None:
        with pytest.raises(KeyError):
            get_resource("NotAnEndpoint")


class TestWaydevSourceResumeBehavior:
    """End-to-end resume behaviour of ``waydev_source`` via ``rest_api_resource``."""

    def _drive(
        self, endpoint: str, manager: mock.MagicMock, responses: list[Response]
    ) -> tuple[mock.MagicMock, list[dict[str, Any]]]:
        sent_params: list[dict[str, Any]] = []
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            sent_params.append(dict(request.params or {}))
            return next(response_iter)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
        ) as mock_session_cls:
            mock_session = mock_session_cls.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = fake_send

            resource = waydev_source(
                api_key="test-key",
                endpoint=endpoint,
                team_id=123,
                job_id="test_job",
                resumable_source_manager=manager,
            )
            list(cast(Iterable[Any], resource))
            return mock_session, sent_params

    def test_incidents_resume_seeds_paginator_with_saved_page(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = WaydevResumeConfig(next_page=5)

        responses = [_make_http_response({"current_page": 5, "data": []})]
        _, sent_params = self._drive("Incidents", manager, responses)

        assert [p.get("page") for p in sent_params] == [5]
        manager.load_state.assert_called_once()

    def test_a_single_real_page_still_probes_once_more_before_stopping(self) -> None:
        # stop_after_empty_page means the last real page is always followed by one more
        # request that comes back empty (no total-pages field is documented for this endpoint).
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        responses = [
            _make_http_response({"current_page": 1, "data": [{"id": 1}]}),
            _make_http_response({"current_page": 2, "data": []}),
        ]
        _, sent_params = self._drive("Incidents", manager, responses)

        assert [p.get("page") for p in sent_params] == [1, 2]
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [WaydevResumeConfig(next_page=2)]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = mock.MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        self._drive("Incidents", manager, [_make_http_response({"current_page": 1, "data": []})])

        manager.load_state.assert_not_called()


class TestValidateCredentials:
    @mock.patch(WAYDEV_SESSION_PATCH)
    def test_ok(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=200)
        assert validate_credentials("token") == (True, 200)
