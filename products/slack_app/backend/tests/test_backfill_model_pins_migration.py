from importlib import import_module

import pytest

from django.apps import apps as live_apps
from django.utils.timezone import now

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.models import SlackSettings, SlackUserProfileCache
from products.tasks.backend.facade.ai_run_defaults import get_user_ai_run_preferences, update_user_ai_run_preferences

# The function is exercised against the live app registry: at HEAD the historical
# models are identical, and this keeps the test at the cheapest level that still
# catches a mapping or conflict-policy regression.
_migration = import_module("products.slack_app.backend.migrations.0016_backfill_model_pins_to_tasks")

WORKSPACE = "T_BACKFILL"
PIN = {"runtime_adapter": "claude", "model": "claude-opus-4-8", "reasoning_effort": "high"}


def _run():
    _migration.backfill_model_pins(live_apps, None)


@pytest.fixture
def setup(db):
    organization = Organization.objects.create(name="Org")
    team_a = Team.objects.create(organization=organization, name="A")
    team_b = Team.objects.create(organization=organization, name="B")
    other_org = Organization.objects.create(name="Other")
    team_outside = Team.objects.create(organization=other_org, name="Outside")
    for team in (team_a, team_b, team_outside):
        Integration.objects.create(
            team=team, kind="slack", integration_id=WORKSPACE, sensitive_config={"access_token": "x"}
        )
    user = User.objects.create_and_join(organization, "pin-owner@example.com", None)
    return user, team_a, team_b, team_outside


def _link(user, slack_user_id="U001", workspace=WORKSPACE):
    UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.SLACK,
        integration_id=slack_user_id,
        config={"slack_team_id": workspace},
    )


def _pin_row(slack_user_id="U001", ai_preferences="use-pin"):
    return SlackSettings.objects.create(
        slack_workspace_id=WORKSPACE,
        slack_user_id=slack_user_id,
        ai_preferences=PIN if ai_preferences == "use-pin" else ai_preferences,
    )


class TestBackfillModelPinsMigration:
    def test_link_mapped_pin_lands_in_every_member_project_and_is_cleared(self, setup):
        user, team_a, team_b, team_outside = setup
        _link(user)
        row = _pin_row()

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id) == PIN
        assert get_user_ai_run_preferences(team_b.id, user.id) == PIN
        # The workspace also connects a project in an org the user isn't in; the
        # pin must not follow it there.
        assert get_user_ai_run_preferences(team_outside.id, user.id) == {}
        row.refresh_from_db()
        assert row.ai_preferences is None

    def test_email_mapped_pin_lands_without_a_link(self, setup):
        user, team_a, _team_b, _team_outside = setup
        integration = Integration.objects.filter(team=team_a, kind="slack").get()
        SlackUserProfileCache.objects.create(
            integration=integration, slack_user_id="U001", email="PIN-OWNER@example.com"
        )
        _pin_row()

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id) == PIN

    def test_newer_central_config_is_kept_but_the_pin_still_clears(self, setup):
        user, team_a, _team_b, _team_outside = setup
        _link(user)
        row = _pin_row()
        update_user_ai_run_preferences(
            team_a.id, user.id, runtime_adapter="codex", model="gpt-5.5", reasoning_effort=None
        )

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id)["model"] == "gpt-5.5"
        row.refresh_from_db()
        assert row.ai_preferences is None

    def test_newer_pin_overwrites_older_central_config(self, setup):
        user, team_a, _team_b, _team_outside = setup
        _link(user)
        update_user_ai_run_preferences(
            team_a.id, user.id, runtime_adapter="codex", model="gpt-5.5", reasoning_effort=None
        )
        _pin_row()

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id) == PIN

    @pytest.mark.parametrize(
        "ai_preferences",
        [
            pytest.param({"reasoning_effort": "high"}, id="half-set-row"),
            pytest.param({}, id="empty-payload"),
        ],
    )
    def test_rows_without_the_atomic_pair_migrate_nothing(self, setup, ai_preferences):
        user, team_a, _team_b, _team_outside = setup
        _link(user)
        _pin_row(ai_preferences=ai_preferences)

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id) == {}

    def test_unmapped_identity_is_left_untouched(self, setup):
        user, team_a, _team_b, _team_outside = setup
        row = _pin_row(slack_user_id="U_NOBODY")

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id) == {}
        row.refresh_from_db()
        assert row.ai_preferences == PIN

    def test_environment_team_pin_lands_on_the_project_root(self, setup):
        user, team_a, _team_b, _team_outside = setup
        env_team = Team.objects.create(
            organization=team_a.organization, project=team_a.project, parent_team=team_a, name="env"
        )
        Integration.objects.create(
            team=env_team, kind="slack", integration_id="T_ENV", sensitive_config={"access_token": "x"}
        )
        _link(user)
        UserIntegration.objects.filter(user=user).update(config={"slack_team_id": "T_ENV"})
        SlackSettings.objects.create(slack_workspace_id="T_ENV", slack_user_id="U001", ai_preferences=PIN)

        _run()

        # Config rows are keyed on the project root, matching the resolver.
        assert get_user_ai_run_preferences(team_a.id, user.id) == PIN

    def test_newer_inaccessible_link_does_not_shadow_the_accessible_one(self, setup):
        user, team_a, _team_b, _team_outside = setup
        _link(user)
        # A newer link on the same Slack identity, held by a user outside every
        # connected org — the runtime resolver skips it, so the migration must too.
        stranger = User.objects.create_and_join(
            Organization.objects.create(name="Elsewhere"), "stranger@example.com", None
        )
        _link(stranger)
        _pin_row()

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id) == PIN
        assert get_user_ai_run_preferences(team_a.id, stranger.id) == {}

    def test_pin_with_only_an_inaccessible_link_is_left_untouched(self, setup):
        user, team_a, _team_b, _team_outside = setup
        stranger = User.objects.create_and_join(
            Organization.objects.create(name="Elsewhere"), "stranger@example.com", None
        )
        _link(stranger)
        row = _pin_row()

        _run()

        row.refresh_from_db()
        assert row.ai_preferences == PIN
        assert get_user_ai_run_preferences(team_a.id, user.id) == {}

    def test_stale_profile_cache_email_loses_to_the_fresh_row(self, setup):
        user, team_a, team_b, _team_outside = setup
        old_owner = User.objects.create_and_join(team_a.organization, "old-address@example.com", None)
        integrations = list(Integration.objects.filter(integration_id=WORKSPACE, team__in=[team_a, team_b]))
        SlackUserProfileCache.objects.create(
            integration=integrations[0], slack_user_id="U001", email="old-address@example.com", refreshed_at=None
        )
        SlackUserProfileCache.objects.create(
            integration=integrations[1], slack_user_id="U001", email="pin-owner@example.com", refreshed_at=now()
        )
        _pin_row()

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id) == PIN
        assert get_user_ai_run_preferences(team_a.id, old_owner.id) == {}

    def test_newest_pin_wins_across_workspaces(self, setup):
        user, team_a, _team_b, _team_outside = setup
        Integration.objects.create(
            team=team_a, kind="slack", integration_id="T_SECOND", sensitive_config={"access_token": "x"}
        )
        _link(user)
        _link(user, slack_user_id="U9", workspace="T_SECOND")
        _pin_row()  # older
        newer = {"runtime_adapter": "codex", "model": "gpt-5.5"}
        SlackSettings.objects.create(slack_workspace_id="T_SECOND", slack_user_id="U9", ai_preferences=newer)

        _run()

        assert get_user_ai_run_preferences(team_a.id, user.id) == newer
