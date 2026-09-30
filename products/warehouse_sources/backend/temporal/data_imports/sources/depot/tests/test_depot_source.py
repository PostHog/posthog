import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot import DEPOT_CI_SERVICE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.source import DepotSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.depot import DepotSourceConfig

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.depot.depot"


def _response(status: int, reason: str, body: dict[str, str | list[str]]) -> Response:
    response = Response()
    response.status_code = status
    response.reason = reason
    response.url = f"{DEPOT_CI_SERVICE_URL}/ListRuns"
    response._content = json.dumps(body).encode()
    return response


class TestDepotSource:
    @pytest.mark.parametrize(
        "repository",
        ["posthog", "https://github.com/PostHog/posthog", "PostHog/posthog/tree/master", "PostHog/ posthog", ""],
    )
    def test_rejects_a_repository_that_is_not_owner_slash_name_without_calling_depot(self, repository: str) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            valid, message = DepotSource().validate_credentials(
                DepotSourceConfig(api_token="token", repository=repository), team_id=1
            )

        assert valid is False
        assert message is not None and "owner/name" in message
        make_session.assert_not_called()

    @pytest.mark.parametrize("repository", ["PostHog/posthog", "example-org/repo.name_2"])
    def test_accepts_an_owner_slash_name_repository_that_depot_lists(self, repository: str) -> None:
        session = mock.MagicMock()
        session.post.return_value = _response(200, "OK", {"runs": []})

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            result = DepotSource().validate_credentials(
                DepotSourceConfig(api_token="token", repository=repository), team_id=1
            )

        assert result == (True, None)

    @pytest.mark.parametrize(
        "status, reason, body",
        [
            (401, "Unauthorized", {"code": "unauthenticated", "message": "invalid token"}),
            (403, "Forbidden", {"code": "permission_denied", "message": "permission denied"}),
        ],
    )
    def test_auth_failures_during_sync_are_non_retryable(
        self, status: int, reason: str, body: dict[str, str | list[str]]
    ) -> None:
        source = DepotSource()
        session = mock.MagicMock()
        session.post.return_value = _response(status, reason, body)
        inputs = mock.MagicMock(should_use_incremental_field=False, history_start=None)

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            response = source.source_for_pipeline(DepotSourceConfig(api_token="token", repository="a/b"), inputs)
            with pytest.raises(HTTPError) as error:
                list(cast(Iterable[list[dict[str, Any]]], response.items()))

        assert any(pattern in str(error.value) for pattern in source.get_non_retryable_errors())
