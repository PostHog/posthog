from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

from requests_mock import Mocker

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onehundredms import (
    OneHundredMsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.onehundredms import (
    OneHundredMsResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onehundredms.source import OneHundredMsSource


@pytest.fixture
def config() -> OneHundredMsSourceConfig:
    return OneHundredMsSourceConfig(
        app_access_key="example-access-key", app_secret="example-secret-for-tests-only-12345"
    )


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


def make_inputs(endpoint: str, incremental: bool = False, watermark: datetime | str | None = None) -> SourceInputs:
    return SourceInputs(
        schema_name=endpoint,
        schema_id="test-schema",
        source_id="test-source",
        team_id=1,
        job_id="test-job",
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
        db_incremental_field_earliest_value=None,
        incremental_field="created_at" if incremental else None,
        incremental_field_type=None,
        logger=MagicMock(),
        reset_pipeline=False,
    )


@pytest.mark.parametrize(
    "endpoint,incremental,watermark,expected",
    [
        ("sessions", True, None, None),
        ("sessions", False, "2026-01-01T00:00:00Z", None),
        ("sessions", True, "2026-01-01T00:00:00.123456Z", "2026-01-01T00:00:00.123Z"),
        ("sessions", True, "2026-01-01T02:00:00+02:00", "2026-01-01T00:00:00.000Z"),
        ("sessions", True, datetime(2026, 1, 1), "2026-01-01T00:00:00.000Z"),
        ("sessions", True, datetime(2026, 1, 1, tzinfo=UTC), "2026-01-01T00:00:00.000Z"),
        ("recordings", True, "2026-01-01T00:00:00Z", None),
        ("live_streams", False, "2026-01-01T00:00:00Z", None),
    ],
)
def test_incremental_filter_is_retained_on_every_page(
    requests_mock: Mocker,
    config: OneHundredMsSourceConfig,
    manager: MagicMock,
    endpoint: str,
    incremental: bool,
    watermark: datetime | str | None,
    expected: str | None,
) -> None:
    requests_mock.get(
        f"https://api.100ms.live/v2/{endpoint.replace('_', '-')}",
        [
            {"json": {"data": [{"id": "example-row"}], "last": "next-cursor"}},
            {"json": {"data": [], "last": None}},
        ],
    )
    response = OneHundredMsSource().source_for_pipeline(config, manager, make_inputs(endpoint, incremental, watermark))
    list(cast(Iterable[Any], response.items()))
    assert requests_mock.call_count == 2
    for request in requests_mock.request_history:
        query = parse_qs(urlsplit(request.url).query)
        assert query.get("after") == ([expected] if expected else None)
    if endpoint == "sessions" and incremental:
        assert response.sort_mode == "desc"


@pytest.mark.parametrize("body", [{"data": [{"id": "row-1"}], "last": "saved-cursor"}, {"unexpected": []}])
def test_invalid_pagination_fails_instead_of_silently_losing_data(
    requests_mock: Mocker, config: OneHundredMsSourceConfig, manager: MagicMock, body: dict[str, Any]
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = OneHundredMsResumeConfig(cursor="saved-cursor")
    requests_mock.get("https://api.100ms.live/v2/recordings", json=body)
    response = OneHundredMsSource().source_for_pipeline(config, manager, make_inputs("recordings"))
    with pytest.raises(ValueError):
        list(cast(Iterable[Any], response.items()))
    assert requests_mock.call_count == 1
    manager.save_state.assert_not_called()


def test_unknown_table_is_rejected(config: OneHundredMsSourceConfig, manager: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        OneHundredMsSource().source_for_pipeline(config, manager, make_inputs("missing"))
