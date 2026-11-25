from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.sources.expo._config import ExpoSourceConfig
from products.warehouse_sources.sources.expo.expo import ExpoAPIError, get_rows
from products.warehouse_sources.sources.expo.source import ExpoSource
from products.warehouse_sources.sources.sdk.testing import error_message_matches

_SOURCE = "products.warehouse_sources.sources.expo.source"
_MODULE = "products.warehouse_sources.sources.expo.expo"


def _sync_error(payload: dict[str, Any]) -> str:
    response = mock.MagicMock()
    response.status_code = 200
    response.json.return_value = payload
    session = mock.MagicMock()
    session.post.return_value = response
    manager = mock.MagicMock()
    manager.can_resume.return_value = False

    with mock.patch(f"{_MODULE}._get_session", return_value=session):
        with pytest.raises(ExpoAPIError) as error:
            list(get_rows("token", "app-1", "builds", mock.MagicMock(), manager))
    return str(error.value)


class TestExpoSourceClass:
    def test_the_project_id_reaches_the_transport(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "builds"

        with mock.patch(f"{_SOURCE}.expo_source") as expo_source:
            ExpoSource().source_for_pipeline(
                ExpoSourceConfig(access_token="token", project_id="app-1"), mock.MagicMock(), inputs
            )

        assert expo_source.call_args.kwargs["project_id"] == "app-1"

    @pytest.mark.parametrize(
        "payload, expected_message_fragment",
        [
            (
                {"errors": [{"message": "Experience with id '00000000-0000-0000-0000-000000000000' does not exist."}]},
                "eas project:info",
            ),
            ({"data": {"app": {"byId": None}}}, "eas project:info"),
            ({"errors": [{"message": "Entity not authorized"}]}, "token's account"),
        ],
        ids=["unknown_project_id", "project_returns_null", "project_not_authorized"],
    )
    def test_a_project_config_error_is_non_retryable(
        self, payload: dict[str, Any], expected_message_fragment: str
    ) -> None:
        error = _sync_error(payload)
        non_retryable = ExpoSource().get_non_retryable_errors()

        matched = [message for pattern, message in non_retryable.items() if error_message_matches(error, [pattern])]
        assert len(matched) == 1, error
        assert expected_message_fragment in (matched[0] or "")

    @pytest.mark.parametrize(
        "message",
        ["Internal server error", "Service temporarily unavailable"],
    )
    def test_a_transient_graphql_error_stays_retryable(self, message: str) -> None:
        error = _sync_error({"errors": [{"message": message}]})

        assert not error_message_matches(error, ExpoSource().get_non_retryable_errors().keys())
