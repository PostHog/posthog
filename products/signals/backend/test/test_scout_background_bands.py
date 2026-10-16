from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Organization, Team, User

from products.signals.backend.models import SignalScoutBackgroundBand, SignalScoutConfig
from products.signals.backend.scout_harness.background_bands import band_for, refresh_background_bands

_NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
_SYNC_EXECUTE = "products.signals.backend.scout_harness.background_bands.sync_execute"


@parameterized.expand(
    [
        ("paying_high_volume", True, 5_000, 3, 1),
        ("paying_mid_volume", True, 4_999, 3, 2),
        ("not_paying", False, 50_000, 3, 3),
        ("stale_login", True, 50_000, 20, 4),
        ("quiet", True, 499, 3, None),
        ("login_too_old", True, 50_000, 31, None),
    ]
)
def test_band_for(_name: str, paying: bool, events_per_day: float, login_days_ago: int, expected: int | None) -> None:
    last_login = _NOW - timedelta(days=login_days_ago)
    assert band_for(paying=paying, events_per_day=events_per_day, last_login=last_login, now=_NOW) == expected


@pytest.mark.django_db
class TestRefreshBackgroundBands:
    def _org_with_member(self, *, paying: bool = True, login_days_ago: int = 1, **org_kwargs) -> tuple[Team, User]:
        org = Organization.objects.create(
            name="band-org", is_ai_data_processing_approved=True, has_active_subscription=paying, **org_kwargs
        )
        team = Team.objects.create(organization=org, name="band-team")
        user = User.objects.create(
            email=f"member-{team.id}@example.com",
            current_team=team,
            current_organization=org,
            last_login=_NOW - timedelta(days=login_days_ago),
        )
        return team, user

    def test_bands_each_org_by_its_most_active_eligible_project(self) -> None:
        paying, _ = self._org_with_member()
        free, _ = self._org_with_member(paying=False)
        # The most active member of this org works in a quieter second project, which holds the band.
        busy_org_team, _ = self._org_with_member()
        second_project = Team.objects.create(organization=busy_org_team.organization, name="second")
        User.objects.create(
            email="recent@example.com",
            current_team=second_project,
            current_organization=busy_org_team.organization,
            last_login=_NOW,
        )
        set_up, _ = self._org_with_member()
        SignalScoutConfig.objects.for_team(set_up.id).create(team=set_up, skill_name="signals-scout-general")
        demo, _ = self._org_with_member()
        Team.objects.filter(id=demo.id).update(is_demo=True)
        internal, _ = self._org_with_member(for_internal_metrics=True)
        stale = SignalScoutBackgroundBand.all_teams.create(
            team=Team.objects.create(organization=paying.organization, name="old"), band=1, computed_at=_NOW
        )

        rows = [(team.id, 7 * 10_000) for team in (paying, free, busy_org_team, set_up, demo, internal)]
        with patch(_SYNC_EXECUTE, return_value=rows):
            outcome = refresh_background_bands(_NOW)

        bands = dict(SignalScoutBackgroundBand.all_teams.values_list("team_id", "band"))
        assert bands == {paying.id: 1, free.id: 3, second_project.id: 1}
        assert not SignalScoutBackgroundBand.all_teams.filter(pk=stale.pk).exists()
        assert outcome.written == 3
