import pytest
from unittest.mock import MagicMock, patch

from posthog.ducklake.models import DuckgresServer
from posthog.models import Organization, Team

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres import enablement
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.enablement import (
    duckgres_sink_team_ids,
)


@pytest.mark.django_db
@patch.object(enablement, "is_dev_mode", return_value=False)
@patch.object(enablement.posthoganalytics, "feature_enabled")
def test_duckgres_sink_flag_evaluated_locally_with_group_properties(
    mock_feature_enabled: MagicMock, _mock_dev: MagicMock
) -> None:
    """The duckgres-batch-sink gate must mirror the data-warehouse-scene call:
    org+project group properties supplied inline and only-local evaluation."""
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    DuckgresServer.objects.create(organization=org, host="h", username="root", password="x")
    mock_feature_enabled.return_value = True

    assert duckgres_sink_team_ids() == [team.id]

    mock_feature_enabled.assert_called_once_with(
        "duckgres-batch-sink",
        str(team.uuid),
        groups={"organization": str(org.id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(org.id)},
            "project": {"id": str(team.id)},
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


@pytest.mark.django_db
@patch.object(enablement, "is_dev_mode", return_value=False)
@patch.object(enablement.posthoganalytics, "feature_enabled")
def test_duckgres_sink_skips_team_when_flag_unresolved_locally(
    mock_feature_enabled: MagicMock, _mock_dev: MagicMock
) -> None:
    """only_evaluate_locally returns None when the flag can't be resolved; that
    falsy value must skip the team, never claim it."""
    org = Organization.objects.create(name="Org")
    Team.objects.create(organization=org)
    DuckgresServer.objects.create(organization=org, host="h", username="root", password="x")
    mock_feature_enabled.return_value = None

    assert duckgres_sink_team_ids() == []
