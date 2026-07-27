import pytest
from unittest.mock import MagicMock, patch

from posthog.ducklake.models import DuckgresServer, DuckgresServerTeam
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
    server = DuckgresServer.objects.create(organization=org, host="h", username="root", password="x")
    DuckgresServerTeam.objects.create(server=server, team=team)
    mock_feature_enabled.return_value = True

    assert duckgres_sink_team_ids() == [team.id]

    mock_feature_enabled.assert_called_once_with(
        "duckgres-batch-sink",
        str(team.uuid),
        groups={"organization": str(org.id), "project": str(team.id)},
        group_properties={
            "organization": {"id": str(org.id)},
            "project": {"id": str(team.id), "organization_id": str(org.id)},
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
    team = Team.objects.create(organization=org)
    server = DuckgresServer.objects.create(organization=org, host="h", username="root", password="x")
    DuckgresServerTeam.objects.create(server=server, team=team)
    mock_feature_enabled.return_value = None

    assert duckgres_sink_team_ids() == []


@pytest.mark.django_db
@patch.object(enablement, "is_dev_mode", return_value=False)
@patch.object(enablement.posthoganalytics, "feature_enabled")
def test_duckgres_sink_enablement_uses_memberships_and_carries_org_budgets(
    mock_feature_enabled: MagicMock, _mock_dev: MagicMock
) -> None:
    """The per-org sink_max_concurrency must ride along with each enabled team,
    or the claim query silently applies no cap (empty mapping = uncapped)."""
    org_a = Organization.objects.create(name="A")
    org_b = Organization.objects.create(name="B")
    team_a = Team.objects.create(organization=org_a)
    team_b = Team.objects.create(organization=org_b)
    Team.objects.create(organization=org_a)
    server_a = DuckgresServer.objects.create(organization=org_a, host="h", username="root", password="x")
    server_b = DuckgresServer.objects.create(
        organization=org_b, host="h", username="root", password="x", sink_max_concurrency=7
    )
    DuckgresServerTeam.objects.create(server=server_a, team=team_a)
    DuckgresServerTeam.objects.create(server=server_b, team=team_b, backfill_enabled=False)
    mock_feature_enabled.return_value = True

    result = enablement.duckgres_sink_enablement()

    assert result is not None
    assert sorted(result.team_ids) == sorted([team_a.id, team_b.id])
    assert set(result.team_org_budgets) == {
        (team_a.id, str(org_a.id), 4),  # model default
        (team_b.id, str(org_b.id), 7),
    }
    # NULL suffix and disabled events backfill do not revoke sink membership;
    # the unregistered third team is never evaluated even though its org is provisioned.
    assert mock_feature_enabled.call_count == 2
