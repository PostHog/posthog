from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.expo.expo import (
    PAGE_SIZE,
    ExpoAPIError,
    ExpoResumeConfig,
    get_rows,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.expo.expo"


def _manager(resume_state: ExpoResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(payload: dict[str, Any], status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code}", response=response)
    return response


def _rows(collection: str, count: int) -> dict[str, Any]:
    return {"data": {"app": {"byId": {"id": "app", collection: [{"id": str(i)} for i in range(count)]}}}}


class TestExpoTransport:
    def test_a_full_page_advances_the_offset(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [_response(_rows("builds", PAGE_SIZE)), _response(_rows("builds", 1))]
        manager = _manager()

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            list(get_rows("token", "app", "builds", mock.MagicMock(), manager))

        assert session.post.call_args_list[1].kwargs["json"]["variables"]["offset"] == PAGE_SIZE
        assert manager.save_state.call_args_list == [mock.call(ExpoResumeConfig(offset=PAGE_SIZE))]

    def test_it_resumes_from_the_saved_offset(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(_rows("builds", 1))

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            list(get_rows("token", "app", "builds", mock.MagicMock(), _manager(ExpoResumeConfig(offset=300))))

        assert session.post.call_args.kwargs["json"]["variables"]["offset"] == 300

    def test_a_graphql_error_in_a_200_response_stops_the_sync(self) -> None:
        # GraphQL reports authorization and validation failures in the body of a 200, so a source
        # that only checks the status code would sync an empty table and call it success.
        session = mock.MagicMock()
        session.post.return_value = _response({"errors": [{"message": "Entity not authorized"}]})

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            with pytest.raises(ExpoAPIError, match="Entity not authorized"):
                list(get_rows("token", "app", "builds", mock.MagicMock(), _manager()))

    def test_a_missing_project_stops_the_sync(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response({"data": {"app": {"byId": None}}})

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            with pytest.raises(ExpoAPIError, match="project not found"):
                list(get_rows("token", "app", "builds", mock.MagicMock(), _manager()))


class TestExpoCredentials:
    def test_a_valid_token_with_project_access_passes(self) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            _response({"data": {"viewer": {"id": "u1", "username": "someone"}}}),
            _response(_rows("builds", 1)),
        ]

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            assert validate_credentials("token", "app") == (True, None)

    def test_a_rejected_token_is_reported(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response({"errors": [{"message": "Unauthorized"}]})

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            valid, message = validate_credentials("token", "app")

        assert valid is False
        assert message is not None and "access token" in message

    @pytest.mark.parametrize(
        "project_response",
        [
            {"errors": [{"message": "Entity not authorized"}]},
            {"data": {"app": {"byId": None}}},
        ],
    )
    def test_a_valid_token_without_project_access_names_the_project(self, project_response: dict[str, Any]) -> None:
        session = mock.MagicMock()
        session.post.side_effect = [
            _response({"data": {"viewer": {"id": "u1"}}}),
            _response(project_response),
        ]

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            valid, message = validate_credentials("token", "app")

        assert valid is False
        assert message is not None and "project ID" in message

    @pytest.mark.parametrize("status_code", [401, 403, 500])
    def test_http_failures_are_reported_rather_than_raised(self, status_code: int) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response({}, status_code=status_code)

        with mock.patch(f"{_MODULE}._get_session", return_value=session):
            valid, message = validate_credentials("token", "app")

        assert valid is False
        assert message is not None
