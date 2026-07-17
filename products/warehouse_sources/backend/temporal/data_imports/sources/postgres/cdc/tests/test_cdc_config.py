import uuid

import pytest

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.config import (
    DEFAULT_LAG_CRITICAL_THRESHOLD_MB,
    DEFAULT_LAG_WARNING_THRESHOLD_MB,
    PostgresCDCConfig,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        ("True", True),
        ("False", False),
        ("true", True),
        (None, False),
        ("__missing__", False),
    ],
)
def test_from_dict_enabled_coercion(value, expected):
    job_inputs = {} if value == "__missing__" else {"cdc_enabled": value}
    assert PostgresCDCConfig.from_dict(job_inputs).enabled is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        ("True", True),
        ("False", False),
        ("true", True),
        (None, False),
        ("__missing__", True),  # defaults to True when the key is absent
    ],
)
def test_from_dict_auto_drop_slot_coercion(value, expected):
    job_inputs = {} if value == "__missing__" else {"cdc_auto_drop_slot": value}
    assert PostgresCDCConfig.from_dict(job_inputs).auto_drop_slot is expected


def test_from_dict_defaults():
    config = PostgresCDCConfig.from_dict(None)
    assert config.enabled is False
    assert config.slot_name == ""
    assert config.publication_name == ""
    assert config.management_mode == "posthog"
    assert config.lag_warning_threshold_mb == DEFAULT_LAG_WARNING_THRESHOLD_MB
    assert config.lag_critical_threshold_mb == DEFAULT_LAG_CRITICAL_THRESHOLD_MB
    assert config.auto_drop_slot is True
    assert config.consistent_point is None


def test_from_dict_thresholds_coerce_stringified_ints():
    config = PostgresCDCConfig.from_dict(
        {"cdc_lag_warning_threshold_mb": "256", "cdc_lag_critical_threshold_mb": "1024"}
    )
    assert config.lag_warning_threshold_mb == 256
    assert config.lag_critical_threshold_mb == 1024


@pytest.mark.django_db
def test_from_source_round_trips_encrypted_booleans(team):
    # job_inputs is an EncryptedJSONField: boolean leaves round-trip as "True"/"False"
    # strings. from_source must decode them back to the right booleans.
    source = ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        status="Completed",
        source_type="Postgres",
        job_inputs={
            "cdc_enabled": True,
            "cdc_auto_drop_slot": False,
            "cdc_slot_name": "posthog_slot",
            "cdc_publication_name": "posthog_pub",
            "cdc_management_mode": "posthog",
        },
    )
    source.refresh_from_db()

    config = PostgresCDCConfig.from_source(source)
    assert config.enabled is True
    assert config.auto_drop_slot is False
    assert config.slot_name == "posthog_slot"
    assert config.publication_name == "posthog_pub"
