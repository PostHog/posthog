from typing import Any
from uuid import uuid4

import pytest
from unittest.mock import patch

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.source_integrations import (
    get_source_integration_ids,
    mark_integration_auth_error,
    resume_syncs_paused_by_auth_failure,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads import META_AUTH_ERROR_MESSAGE
from products.warehouse_sources.backend.types import ExternalDataSchemaStatus, ExternalDataSourceType

pytestmark = [pytest.mark.django_db]


@pytest.fixture
def team() -> Any:
    return create_team(create_organization("Test org"))


def _integration(team: Any) -> Integration:
    return Integration.objects.create(team=team, kind="meta-ads", integration_id="act_1")


def _source(team: Any, integration: Integration) -> ExternalDataSource:
    return ExternalDataSource.objects.create(
        team=team,
        source_id=str(uuid4()),
        connection_id=str(uuid4()),
        source_type=ExternalDataSourceType.METAADS,
        job_inputs={"meta_ads_integration_id": integration.id, "account_id": "act_1"},
    )


def _schema(team: Any, source: ExternalDataSource, *, name: str, error: str | None, status: str | None) -> Any:
    return ExternalDataSchema.objects.create(
        team=team, source=source, name=name, should_sync=False, latest_error=error, status=status
    )


def test_reads_every_integration_id_a_source_holds(team: Any) -> None:
    integration = _integration(team)
    source = _source(team, integration)
    source.job_inputs = {**source.job_inputs, "github_integration_id": "77", "prefix": "not_an_id"}

    assert get_source_integration_ids(source) == {integration.id, 77}


def test_auth_failure_marks_the_connected_integration(team: Any) -> None:
    integration = _integration(team)
    source = _source(team, integration)

    mark_integration_auth_error(source)

    integration.refresh_from_db()
    assert integration.errors == ERROR_TOKEN_REFRESH_FAILED


def test_reconnect_resumes_only_the_tables_the_auth_failure_stopped(team: Any) -> None:
    integration = _integration(team)
    source = _source(team, integration)
    auth_stopped = _schema(
        team, source, name="campaigns", error=META_AUTH_ERROR_MESSAGE, status=ExternalDataSchemaStatus.FAILED
    )
    other_failure = _schema(
        team, source, name="ads", error="Meta could not return this data", status=ExternalDataSchemaStatus.FAILED
    )
    turned_off_by_user = _schema(team, source, name="adsets", error=None, status=ExternalDataSchemaStatus.COMPLETED)

    with patch("products.warehouse_sources.backend.source_integrations.update_should_sync") as mock_update_should_sync:
        resumed = resume_syncs_paused_by_auth_failure(integration_id=integration.id, team_id=team.id)

    assert resumed == 1
    assert mock_update_should_sync.call_count == 1
    assert mock_update_should_sync.call_args.kwargs["schema_id"] == str(auth_stopped.id)
    other_failure.refresh_from_db()
    turned_off_by_user.refresh_from_db()
    assert other_failure.should_sync is False
    assert turned_off_by_user.should_sync is False


def test_reconnect_leaves_another_integrations_sources_alone(team: Any) -> None:
    integration = _integration(team)
    source = _source(team, integration)
    _schema(team, source, name="campaigns", error=META_AUTH_ERROR_MESSAGE, status=ExternalDataSchemaStatus.FAILED)

    with patch("products.warehouse_sources.backend.source_integrations.update_should_sync") as mock_update_should_sync:
        resumed = resume_syncs_paused_by_auth_failure(integration_id=integration.id + 1, team_id=team.id)

    assert resumed == 0
    assert mock_update_should_sync.call_count == 0
