import uuid

import pytest

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.typeform.schema_transition import (
    apply_typeform_response_types_reset,
    detect_typeform_response_types_transition,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

TYPEFORM = ExternalDataSourceType.TYPEFORM
PARTIALS = "completed,partial,started"


@pytest.mark.parametrize(
    "_name,source_type,existing,incoming,expected",
    [
        ("flip_to_partials", TYPEFORM, {"response_types": "completed"}, {"response_types": PARTIALS}, True),
        # An absent existing value means the default (completed), so explicit partials is a change.
        ("default_to_partials", TYPEFORM, {}, {"response_types": PARTIALS}, True),
        ("unchanged", TYPEFORM, {"response_types": "completed"}, {"response_types": "completed"}, False),
        # PATCH that doesn't touch response_types must never reset, whatever else it changes.
        ("response_types_absent", TYPEFORM, {"response_types": PARTIALS}, {"auth_token": "x"}, False),
        (
            "non_typeform",
            ExternalDataSourceType.POSTGRES,
            {"response_types": "completed"},
            {"response_types": PARTIALS},
            False,
        ),
    ],
)
def test_detect_typeform_response_types_transition(_name, source_type, existing, incoming, expected):
    assert (
        detect_typeform_response_types_transition(
            source_type=source_type, existing_job_inputs=existing, incoming_job_inputs=incoming
        )
        is expected
    )


def _typeform_source(team) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        status="Completed",
        source_type="Typeform",
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "incoming_response_types,expected_sync_type,expect_submitted_at_cursor",
    [
        (PARTIALS, ExternalDataSchema.SyncType.FULL_REFRESH, False),
        ("completed", ExternalDataSchema.SyncType.INCREMENTAL, True),
    ],
)
def test_apply_typeform_response_types_reset(
    team, incoming_response_types, expected_sync_type, expect_submitted_at_cursor
):
    source = _typeform_source(team)
    responses = ExternalDataSchema.objects.create(
        team_id=team.pk,
        source=source,
        name="responses",
        should_sync=True,
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={
            "incremental_field": "submitted_at",
            "incremental_field_type": "DateTime",
            "incremental_field_last_value": "2026-06-20T00:00:00Z",
            "incremental_field_earliest_value": "2025-09-22T00:00:00Z",
        },
    )
    forms = ExternalDataSchema.objects.create(
        team_id=team.pk,
        source=source,
        name="forms",
        should_sync=True,
        sync_type=ExternalDataSchema.SyncType.INCREMENTAL,
        sync_type_config={"incremental_field": "last_updated_at"},
    )

    reset = apply_typeform_response_types_reset(source, incoming_job_inputs={"response_types": incoming_response_types})

    # Only the responses schema is reset — forms is left untouched.
    assert [s.id for s in reset] == [responses.id]

    responses.refresh_from_db()
    assert responses.sync_type == expected_sync_type
    assert responses.sync_type_config["reset_pipeline"] is True
    # The stale watermark is always cleared so the rebuilt table starts fresh.
    assert "incremental_field_last_value" not in responses.sync_type_config
    assert "incremental_field_earliest_value" not in responses.sync_type_config
    if expect_submitted_at_cursor:
        assert responses.sync_type_config["incremental_field"] == "submitted_at"
    else:
        assert "incremental_field" not in responses.sync_type_config

    forms.refresh_from_db()
    assert forms.sync_type == ExternalDataSchema.SyncType.INCREMENTAL
    assert forms.sync_type_config == {"incremental_field": "last_updated_at"}
