from dataclasses import replace

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres import enablement
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.enablement import (
    is_duckgres_sink_team_member,
)


def _cp_row(team: Team, *, backfill_enabled: bool = True) -> ManagedWarehouseTeamMembership:
    schema_name = f"team_{team.id}"
    return ManagedWarehouseTeamMembership(
        team_id=team.id,
        organization_id=str(team.organization_id),
        schema_name=schema_name,
        enabled=True,
        backfill_enabled=backfill_enabled,
        table_names=ManagedWarehouseTableNames(
            events_table=f"events_{schema_name}",
            persons_table=f"persons_{schema_name}",
            data_imports_schema=f"posthog_data_imports_{schema_name}",
        ),
        earliest_event_date=None,
    )


def _patch_all_rows(rows: list[ManagedWarehouseTeamMembership] | None):
    return patch.object(enablement, "list_team_memberships", return_value=rows)


def _patch_budgets(budgets: dict[str, int]):
    return patch.object(enablement, "sink_concurrency_by_trusted_organization_ids", return_value=budgets)


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
    mock_feature_enabled.return_value = True

    with _patch_all_rows([_cp_row(team)]), _patch_budgets({str(org.id): 4}):
        result = enablement.duckgres_sink_enablement()

    assert result is not None
    assert result.team_ids == [team.id]

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
    mock_feature_enabled.return_value = None

    with _patch_all_rows([_cp_row(team)]), _patch_budgets({str(org.id): 4}):
        result = enablement.duckgres_sink_enablement()

    assert result is not None
    assert result.team_ids == []


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
    mock_feature_enabled.return_value = True

    # Disabled events backfill does not revoke sink membership; the unregistered third
    # team is never evaluated even though its org is provisioned.
    with (
        _patch_all_rows([_cp_row(team_a), _cp_row(team_b, backfill_enabled=False)]),
        _patch_budgets({str(org_a.id): 4, str(org_b.id): 7}),
    ):
        result = enablement.duckgres_sink_enablement()

    assert result is not None
    assert sorted(result.team_ids) == sorted([team_a.id, team_b.id])
    assert set(result.team_org_budgets) == {
        (team_a.id, str(org_a.id), 4),  # model default
        (team_b.id, str(org_b.id), 7),
    }
    assert mock_feature_enabled.call_count == 2


@pytest.mark.django_db
@patch.object(enablement, "is_dev_mode", return_value=False)
@patch.object(enablement.posthoganalytics, "feature_enabled")
def test_duckgres_sink_enablement_ignores_non_uuid_control_plane_org_ids(
    mock_feature_enabled: MagicMock, _mock_dev: MagicMock
) -> None:
    """The control plane can report extra rows for a team keyed by a non-UUID
    organization_id (e.g. dev/test rows using human-readable slugs instead of a real
    org id). Those must not crash the whole refresh via a Django UUID lookup — they
    should just fail the org match-up and be skipped, like any other mismatched row."""
    org = Organization.objects.create(name="Org")
    team = Team.objects.create(organization=org)
    mock_feature_enabled.return_value = True

    mismatched_row = replace(_cp_row(team), organization_id="not-a-uuid-slug")

    with _patch_all_rows([_cp_row(team), mismatched_row]), _patch_budgets({str(org.id): 4}):
        result = enablement.duckgres_sink_enablement()

    assert result is not None
    assert result.team_ids == [team.id]
    mock_feature_enabled.assert_called_once()


@pytest.mark.django_db
@patch.object(enablement, "is_dev_mode", return_value=False)
@patch.object(enablement.posthoganalytics, "feature_enabled")
def test_duckgres_sink_enablement_raises_when_control_plane_unreachable(
    mock_feature_enabled: MagicMock, _mock_dev: MagicMock
) -> None:
    # The consumer keeps its previous cached enablement on a raise; returning an empty
    # enablement instead would silently stop the sink fleet-wide on a CP blip.
    with _patch_all_rows(None):
        with pytest.raises(RuntimeError):
            enablement.duckgres_sink_enablement()

    mock_feature_enabled.assert_not_called()


@pytest.mark.django_db
def test_is_duckgres_sink_team_member_reads_the_control_plane() -> None:
    org = Organization.objects.create(name="Org")
    member = Team.objects.create(organization=org)
    non_member = Team.objects.create(organization=org)

    with patch.object(enablement, "list_org_team_memberships", return_value=[_cp_row(member)]):
        assert is_duckgres_sink_team_member(member.id) is True
        assert is_duckgres_sink_team_member(non_member.id) is False

    with patch.object(enablement, "list_org_team_memberships", return_value=None):
        with pytest.raises(RuntimeError):
            is_duckgres_sink_team_member(member.id)
