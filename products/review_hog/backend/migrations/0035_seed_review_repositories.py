from django.conf import settings
from django.db import migrations

# The repositories the hardcoded allowlists covered: automatic Flash reviews ran only in
# PostHog/posthog, and the label trigger also accepted PostHog/ai-gateway. The first ReviewHog team
# selects both, so automatic reviews and the label trigger keep their project. The project rule
# stays at its default, opt-in only, so only people who chose Flash get it.
SEEDED_REPOSITORIES = ("PostHog/posthog", "PostHog/ai-gateway")


def _preferences_from_columns(row) -> dict:
    """The row's non-default values, against the defaults of the preferences schema.

    `resolve_comments` copies nothing: resolution becomes opt-in for everyone, also for rows that
    kept the old default of on.
    """
    preferences: dict = {}
    if row.review_authored_prs:
        preferences["default_review_mode"] = "flash"
    if row.urgency_threshold != "consider":
        preferences["urgency_threshold"] = row.urgency_threshold
    if not row.celebrate_clean_reviews:
        preferences["celebrate_clean_reviews"] = False
    if row.review_inbox_prs:
        preferences["review_inbox_prs"] = True
    if row.stamphog_review_inbox_prs:
        preferences["stamphog_review_inbox_prs"] = True
    return preferences


def copy_settings_into_preferences(apps, schema_editor):
    ReviewUserSettings = apps.get_model("review_hog", "ReviewUserSettings")
    for row in ReviewUserSettings.objects.all().iterator():
        preferences = _preferences_from_columns(row)
        if preferences:
            row.preferences = preferences
            row.save(update_fields=["preferences"])
        else:
            # Nothing differs from the defaults. No repository choice can exist yet, because 0034
            # creates that table, so the row carries nothing.
            row.delete()


def _seed_repository_rows(apps, team_id: int) -> None:
    Integration = apps.get_model("posthog", "Integration")
    ReviewInstallationClaim = apps.get_model("review_hog", "ReviewInstallationClaim")
    ReviewRepository = apps.get_model("review_hog", "ReviewRepository")

    wanted = {full_name.lower(): full_name for full_name in SEEDED_REPOSITORIES}
    for integration in Integration.objects.filter(team_id=team_id, kind="github").order_by("id"):
        cached = integration.repository_cache if isinstance(integration.repository_cache, list) else []
        found = {
            str(repository.get("full_name", "")).lower(): repository
            for repository in cached
            if isinstance(repository, dict)
        }
        matches = [found[name] for name in wanted if name in found]
        if not matches or not integration.integration_id:
            continue
        installation_id = integration.integration_id
        ReviewInstallationClaim.objects.get_or_create(
            team_id=team_id, installation_id=installation_id, defaults={"scope": "selected"}
        )
        for repository in matches:
            full_name = str(repository["full_name"])
            github_repo_id = repository.get("id") if isinstance(repository.get("id"), int) else None
            if ReviewRepository.objects.filter(installation_id=installation_id, full_name__iexact=full_name).exists():
                continue
            ReviewRepository.objects.create(
                team_id=team_id,
                installation_id=installation_id,
                github_repo_id=github_repo_id,
                full_name=full_name,
                selected=True,
            )
        return


def seed_review_settings(apps, schema_editor):
    copy_settings_into_preferences(apps, schema_editor)

    # Only the first ReviewHog team received automatic and label-triggered reviews. Other instances
    # leave the setting empty, or name a team that does not exist there.
    if not settings.REVIEWHOG_TEAM_IDS:
        return
    team_id = settings.REVIEWHOG_TEAM_IDS[0]
    Team = apps.get_model("posthog", "Team")
    if not Team.objects.filter(id=team_id).exists():
        return
    _seed_repository_rows(apps, team_id)


class Migration(migrations.Migration):
    dependencies = [
        ("review_hog", "0034_review_repositories"),
    ]

    # Separate from 0034, so the data writes never share a transaction with the schema change.
    # The tables are small: one settings row per user, and at most two repositories.
    operations = [
        migrations.RunPython(seed_review_settings, migrations.RunPython.noop, elidable=True),
    ]
