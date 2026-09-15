from django.db import migrations
from django.db.models import F


def backfill_model_pins(apps, schema_editor):
    """Move personal Slack model pins into the central per-(user, project) tasks config.

    The App Home now writes model preferences only to that config (the Slack-local pin
    store is being retired), so pins that predate the switch are copied over and cleared
    here. A pin lands in every connected project where its owner is a member, matching
    how it used to apply regardless of routing. Conflicts resolve most-recent-wins on
    ``updated_at``, so a central preference set, or deliberately cleared, after the pin
    keeps its value; rows are walked oldest first so a user pinned in several workspaces
    deterministically ends on their newest pin.

    The Slack identity resolves the same two ways the inbound event path maps it, with
    the same organization scope: the newest account link whose user belongs to a
    connected organization, else a profile-cache email match against those members. A
    pin that maps to no user or to no member project is left in place — it cannot
    influence a run (mentions from unresolved users are dropped) and goes away with the
    column.

    Model ids and efforts are copied as stored, without catalogue validation: run
    resolution is lenient about stale ids, and a migration must not depend on a live
    model catalogue.
    """
    SlackSettings = apps.get_model("slack_app", "SlackSettings")
    SlackUserProfileCache = apps.get_model("slack_app", "SlackUserProfileCache")
    Integration = apps.get_model("posthog", "Integration")
    OrganizationMembership = apps.get_model("posthog", "OrganizationMembership")
    Team = apps.get_model("posthog", "Team")
    UserIntegration = apps.get_model("posthog", "UserIntegration")
    UserTasksConfig = apps.get_model("tasks", "UserTasksConfig")

    def connected_teams(workspace_id):
        """(team_id, organization_id) pairs of every project this workspace connects."""
        return list(
            Integration.objects.filter(kind="slack", integration_id=workspace_id).values_list(
                "team_id", "team__organization_id"
            )
        )

    def resolve_user(workspace_id, slack_user_id, org_ids):
        """The PostHog user behind a Slack identity, scoped like the inbound event
        resolver: the newest account link whose user belongs to a connected
        organization, else a profile-cache email match against those members."""
        links = list(
            UserIntegration.objects.filter(
                kind="slack",
                integration_id=slack_user_id,
                config__slack_team_id=workspace_id,
                user__is_active=True,
            )
            .order_by("-created_at")
            .select_related("user")
        )
        member_ids = set(
            OrganizationMembership.objects.filter(
                user_id__in=[link.user_id for link in links], organization_id__in=org_ids
            ).values_list("user_id", flat=True)
        )
        for link in links:
            if link.user_id in member_ids:
                return link.user

        # Freshest cache row first; rows predating `refreshed_at` sort last.
        email = (
            SlackUserProfileCache.objects.filter(
                integration__kind="slack",
                integration__integration_id=workspace_id,
                slack_user_id=slack_user_id,
            )
            .exclude(email=None)
            .exclude(email="")
            .order_by(F("refreshed_at").desc(nulls_last=True), "-updated_at")
            .values_list("email", flat=True)
            .first()
        )
        if not email:
            return None
        membership = (
            OrganizationMembership.objects.filter(
                organization_id__in=org_ids, user__email__iexact=email, user__is_active=True
            )
            .select_related("user")
            .first()
        )
        return membership.user if membership else None

    def member_canonical_team_ids(teams, user):
        """Teams among ``teams`` whose organization the user belongs to, keyed on the
        project root team like the config rows themselves."""
        member_org_ids = set(
            OrganizationMembership.objects.filter(
                user=user, organization_id__in={org_id for _, org_id in teams}
            ).values_list("organization_id", flat=True)
        )
        member_team_ids = {team_id for team_id, org_id in teams if org_id in member_org_ids}
        pairs = Team.objects.filter(id__in=member_team_ids).values_list("id", "parent_team_id")
        return sorted({parent_id or team_id for team_id, parent_id in pairs})

    # Oldest first, so when one user holds pins in several workspaces the newest
    # pin is applied last and wins.
    rows = SlackSettings.objects.filter(
        slack_user_id__isnull=False,
        ai_preferences__isnull=False,
    ).order_by("updated_at", "id")
    migrated_keys = set()
    for row in rows.iterator():
        prefs = row.ai_preferences or {}
        # Both halves of the pair or the row was never a configured pin.
        payload = {key: prefs[key] for key in ("runtime_adapter", "model", "reasoning_effort") if prefs.get(key)}
        if "runtime_adapter" not in payload or "model" not in payload:
            continue
        teams = connected_teams(row.slack_workspace_id)
        user = resolve_user(row.slack_workspace_id, row.slack_user_id, {org_id for _, org_id in teams})
        if user is None:
            continue
        team_ids = member_canonical_team_ids(teams, user)
        if not team_ids:
            # No destination: keep the pin rather than discarding a preference
            # this migration could not place anywhere.
            continue
        for team_id in team_ids:
            key = (team_id, user.id)
            config = UserTasksConfig._base_manager.filter(team_id=team_id, user_id=user.id).first()
            # A pre-existing config newer than the pin wins; one written by this
            # run does not, so a user's newest pin ends up applied.
            if config is not None and key not in migrated_keys and config.updated_at >= row.updated_at:
                continue
            if config is None:
                UserTasksConfig._base_manager.create(team_id=team_id, user_id=user.id, ai_run_preferences=payload)
            else:
                config.ai_run_preferences = payload
                config.save(update_fields=["ai_run_preferences", "updated_at"])
            migrated_keys.add(key)
        # Accounted for on every reachable project; clear the pin so display and
        # runs stop preferring a store that no longer takes writes.
        row.ai_preferences = None
        row.save(update_fields=["ai_preferences", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0015_backfill_slack_thread_conversation_type"),
        # UserTasksConfig and the posthog identity models the mapping reads.
        ("tasks", "0115_teamtasksconfig_usertasksconfig"),
        ("posthog", "0001_squash_2026_09_07_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_model_pins, migrations.RunPython.noop, elidable=True),
    ]
