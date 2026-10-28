from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.youtubedata import (
    YoutubeDataSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.youtube_data.source import YoutubeDataSource


@pytest.mark.parametrize(
    ("status", "body", "expected_error"),
    [
        (200, {"items": [{"id": "UC_example"}]}, None),
        (200, {"items": []}, "YouTube channel was not found."),
        (
            400,
            {"error": {"message": "API key not valid. Please pass a valid API key."}},
            "YouTube rejected the request.",
        ),
        (401, {"error": {"errors": [{"reason": "authError"}]}}, "YouTube credentials are invalid or expired."),
        (403, {"error": {"errors": [{"reason": "accessNotConfigured"}]}}, "YouTube access was denied."),
        (403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}, "YouTube quota exceeded."),
        (403, {"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}, "YouTube quota exceeded."),
        (404, {"error": {"errors": [{"reason": "channelNotFound"}]}}, "YouTube could not find the requested data."),
    ],
)
def test_credential_probe_maps_vendor_errors_without_exposing_key(
    status: int, body: dict[str, Any], expected_error: str | None
) -> None:
    config = YoutubeDataSourceConfig(api_key="fake-secret-key", channel_id="UC_example")
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        valid, message = YoutubeDataSource().validate_credentials(config, team_id=1)

    assert valid == (expected_error is None)
    if expected_error is None:
        assert message is None
    else:
        assert message is not None and message.startswith(expected_error)
        assert "fake-secret-key" not in message
    assert len(network.requests_log) == 1
    assert network.requests_log[0].param("part") == "contentDetails"
    assert network.requests_log[0].param("id") == "UC_example"


def test_unknown_schema_rejects_credentials_without_a_probe() -> None:
    config = YoutubeDataSourceConfig(api_key="fake-secret-key", channel_id="UC_example")
    with scripted_network([]) as network:
        result = YoutubeDataSource().validate_credentials(config, team_id=1, schema_name="unknown")

    assert result == (False, "Unsupported YouTube table: unknown")
    assert network.requests_log == []


@pytest.mark.parametrize(
    ("reason", "expected_error"),
    [
        ("commentsDisabled", "YouTube comments are disabled."),
        ("quotaExceeded", "YouTube quota exceeded."),
        ("forbidden", "YouTube access was denied."),
    ],
)
def test_comment_failures_stop_sync_with_actionable_error(reason: str, expected_error: str) -> None:
    config = YoutubeDataSourceConfig(api_key="fake-secret-key", channel_id="UC_example")
    result = SourceDriver(YoutubeDataSource(), config).run(
        "comment_threads", [ScriptedResponse(status=403, json={"error": {"errors": [{"reason": reason}]}})]
    )

    assert isinstance(result.raised, ValueError)
    assert str(result.raised).startswith(expected_error)
    assert "fake-secret-key" not in str(result.raised)
    assert result.rows == []
