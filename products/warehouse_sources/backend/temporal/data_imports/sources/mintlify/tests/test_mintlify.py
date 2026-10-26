from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mintlify import (
    MintlifySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.mintlify import (
    MintlifyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.source import MintlifySource


@pytest.fixture
def config() -> MintlifySourceConfig:
    return MintlifySourceConfig(api_key="mint_example_fake_key", project_id="example-project")


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected"),
    [
        (True, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00+00:00"),
        (True, "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
        (True, None, None),
        (False, "2026-01-01T00:00:00Z", None),
    ],
)
def test_incremental_date_filter(
    config: MintlifySourceConfig,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    result = SourceDriver(MintlifySource(), config).run(
        "assistant_conversations",
        [
            ScriptedResponse(json={"conversations": [{"id": "turn-1"}], "nextCursor": "cursor-2"}),
            ScriptedResponse(json={"conversations": [], "nextCursor": None}),
        ],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )
    assert result.raised is None
    assert result.rows == [{"id": "turn-1"}]
    assert result.params("cursor") == [None, "cursor-2"]
    assert result.params("dateFrom") == [expected, expected]
    if incremental:
        assert result.response is not None
        assert result.response.sort_mode == "desc"


@pytest.mark.parametrize(
    ("endpoint", "selector", "state", "parameter", "value"),
    [
        ("assistant_conversations", "conversations", {"cursor": "saved-cursor"}, "cursor", "saved-cursor"),
        ("views", "views", {"offset": 750}, "offset", "750"),
    ],
)
def test_resume_preserves_window(
    config: MintlifySourceConfig,
    endpoint: str,
    selector: str,
    state: dict[str, Any],
    parameter: str,
    value: str,
) -> None:
    result = SourceDriver(MintlifySource(), config).run(
        endpoint,
        [ScriptedResponse(json={selector: [], "nextCursor": None, "hasMore": False})],
        resume_state=MintlifyResumeConfig(paginator_state=state, date_to="2026-01-02T00:00:00Z", date_from=None),
    )
    assert result.raised is None
    assert result.params(parameter) == [value]
    assert result.params("dateTo") == ["2026-01-02T00:00:00Z"]
    assert result.params("dateFrom") == [None]
    assert result.saved_states == []


@pytest.mark.parametrize("status", [400, 404])
def test_credentials_and_terminal_errors(config: MintlifySourceConfig, status: int) -> None:
    body: dict[str, Any] = {"feedback": []} if status == 200 else {"error": "Unauthorized"}
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        valid, message = validate_credentials(config)
    assert valid is (status == 200)
    if status != 200:
        assert message
        assert message == MintlifySource().get_non_retryable_errors()[f"{status} Client Error"]
    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.headers["authorization"] == "Bearer mint_example_fake_key"
    assert request.query == {"limit": ("1",)}


@pytest.mark.parametrize("status", [429, 500])
def test_transient_errors_stay_retryable(config: MintlifySourceConfig, status: int) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={"error": "Unavailable"}))) as network:
        with pytest.raises(RESTClientRetryableError):
            validate_credentials(config)
    assert network.requests_log
    assert {request.path for request in network.requests_log} == {"/v1/analytics/example-project/feedback"}
    assert not any(str(status) in key for key in MintlifySource().get_non_retryable_errors())


def test_unknown_table_fails_before_request(config: MintlifySourceConfig) -> None:
    result = SourceDriver(MintlifySource(), config).run("unknown", [])
    assert isinstance(result.raised, UnknownResourceError)
    assert result.requests == []
    with scripted_network([]) as network:
        with pytest.raises(UnknownResourceError):
            validate_credentials(config, "unknown")
    assert network.requests_log == []


def test_project_id_cannot_change_request_path(config: MintlifySourceConfig) -> None:
    config.project_id = "example/other?limit=5#fragment"
    result = SourceDriver(MintlifySource(), config).run(
        "feedback", [ScriptedResponse(json={"feedback": [], "nextCursor": None})]
    )
    assert result.raised is None
    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.origin == "https://api.mintlify.com"
    assert request.path == "/v1/analytics/example%2Fother%3Flimit%3D5%23fragment/feedback"
    assert request.param("limit") == "100"


def test_source_adapter_delegates_to_mintlify_transport(config: MintlifySourceConfig) -> None:
    source = MintlifySource()
    inputs = MagicMock(
        schema_name="assistant_conversations",
        team_id=1,
        job_id="job",
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
    )
    manager = source.get_resumable_source_manager(inputs)

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.source.validate_credentials",
        return_value=(True, None),
    ) as validate:
        assert source.validate_credentials(config, 1, "feedback") == (True, None)
        validate.assert_called_once_with(config, "feedback")

    expected = MagicMock()
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mintlify.source.mintlify_source",
        return_value=expected,
    ) as build_source:
        assert source.source_for_pipeline(config, manager, inputs) is expected
        build_source.assert_called_once_with(
            config=config,
            endpoint_name="assistant_conversations",
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
