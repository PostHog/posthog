from typing import Any

import pytest
from unittest.mock import patch

from django.db import OperationalError
from django.test import override_settings

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.scheduling import backend
from products.warehouse_sources.backend.scheduling.backend import (
    QUEUE_SCHEDULER_FLAG,
    queue_scheduler_firing_enabled,
    queue_scheduler_teams,
)

FEATURE_ENABLED = "posthoganalytics.feature_enabled"


@pytest.mark.parametrize("value", [True, False])
def test_firing_kill_switch_reads_setting(value: bool) -> None:
    with override_settings(WAREHOUSE_QUEUE_SCHEDULER_FIRING_ENABLED=value):
        assert queue_scheduler_firing_enabled() is value


def test_firing_kill_switch_defaults_off() -> None:
    assert queue_scheduler_firing_enabled() is False


@pytest.mark.django_db
class TestQueueSchedulerTeams:
    @pytest.mark.parametrize(
        "answer,routed",
        [
            pytest.param(True, True, id="flag_on"),
            pytest.param(False, False, id="flag_off"),
            # Local evaluation answers None when it cannot decide, for example before the flags load.
            pytest.param(None, False, id="not_evaluable_locally"),
            pytest.param(RuntimeError("flags down"), False, id="error"),
        ],
    )
    def test_evaluates_the_flag_per_team_and_locally(self, answer: Any, routed: bool) -> None:
        organization = create_organization("routing org")
        team = create_team(organization=organization)

        with patch(FEATURE_ENABLED, side_effect=[answer]) as flag:
            assert queue_scheduler_teams([team.pk, team.pk]) == ({team.pk} if routed else frozenset())

        flag.assert_called_once_with(
            QUEUE_SCHEDULER_FLAG,
            str(team.uuid),
            groups={"organization": str(organization.id), "project": str(team.pk)},
            person_properties={"team_id": str(team.pk)},
            group_properties={"organization": {"id": str(organization.id)}, "project": {"id": str(team.pk)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
            disable_geoip=None,
            device_id=None,
        )

    def test_routes_only_flagged_teams_across_lookup_batches(self) -> None:
        organization = create_organization("routing org")
        teams = [create_team(organization=organization) for _ in range(3)]
        flagged = {str(teams[0].uuid), str(teams[2].uuid)}

        with (
            patch.object(backend, "_TEAM_LOOKUP_BATCH_SIZE", 2),
            patch(FEATURE_ENABLED, side_effect=lambda flag, distinct_id, **_: distinct_id in flagged),
        ):
            # A team that no longer exists is not routed and costs no evaluation.
            assert queue_scheduler_teams([team.pk for team in teams] + [987654321]) == {teams[0].pk, teams[2].pk}

    def test_a_team_lookup_failure_propagates(self) -> None:
        with patch.object(backend.Team.objects, "filter", side_effect=OperationalError("db down")):
            with pytest.raises(OperationalError):
                queue_scheduler_teams([1])
