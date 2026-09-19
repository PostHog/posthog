import datetime as dt

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sync_failure_events import (
    MAX_ERROR_LENGTH,
    WAREHOUSE_SOURCE_SYNC_FAILED_EVENT,
    produce_sync_failed_events,
)

_PRODUCE_INTERNAL_EVENT = (
    "products.warehouse_sources.backend.temporal.data_imports.sync_failure_events.produce_internal_event"
)


def _source(**fields) -> ExternalDataSource:
    return ExternalDataSource(team_id=1, source_type="Slack", prefix="community_", **fields)


def _schema(source: ExternalDataSource, **fields) -> ExternalDataSchema:
    return ExternalDataSchema(team_id=1, source=source, name="C0123456", **fields)


@pytest.mark.parametrize(
    "schema_fields,source_fields,expected_paused",
    [
        ({"should_sync": True}, {}, False),
        ({"should_sync": True, "sync_type_config": {"cdc_broken": {"reason": "slot_missing"}}}, {}, True),
        ({"should_sync": False, "auto_disabled_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC)}, {}, True),
        ({"should_sync": False}, {}, None),
        ({"should_sync": True, "deleted": True}, {}, None),
        ({"should_sync": True}, {"deleted": True}, None),
    ],
)
def test_produces_an_event_unless_the_digest_skips_the_schema(schema_fields, source_fields, expected_paused):
    source = _source(**source_fields)
    schema = _schema(source, label="general", **schema_fields)

    with patch(_PRODUCE_INTERNAL_EVENT) as mock_produce:
        produce_sync_failed_events(source, [schema], "x" * (MAX_ERROR_LENGTH + 500), job_id="job-1")

    if expected_paused is None:
        mock_produce.assert_not_called()
        return

    mock_produce.assert_called_once()
    assert mock_produce.call_args.kwargs["team_id"] == 1
    event = mock_produce.call_args.kwargs["event"]
    assert event.event == WAREHOUSE_SOURCE_SYNC_FAILED_EVENT
    assert event.properties == {
        "source_id": str(source.id),
        "source_type": "Slack",
        "source_prefix": "community",
        "schema_id": str(schema.id),
        "schema_name": "general",
        "job_id": "job-1",
        "error": "x" * MAX_ERROR_LENGTH,
        "sync_paused": expected_paused,
    }


def test_a_produce_error_does_not_raise_or_skip_the_remaining_schemas():
    source = _source()
    schemas = [_schema(source, should_sync=True), _schema(source, should_sync=True)]

    with patch(_PRODUCE_INTERNAL_EVENT, side_effect=[Exception("kafka unavailable"), None]) as mock_produce:
        produce_sync_failed_events(source, schemas, "boom")

    assert mock_produce.call_count == 2
