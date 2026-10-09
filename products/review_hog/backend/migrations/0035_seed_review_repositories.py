from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

# The repositories the hardcoded allowlists covered: automatic Flash reviews ran only in
# PostHog/posthog, and the label trigger also accepted PostHog/ai-gateway. The project that ran those
# automatic reviews selects both, so automatic reviews and the label trigger keep their project. The
# project rule stays at its default, opt-in only, so only people who chose Flash get it.
SEEDED_ACCOUNT = "PostHog"
SEEDED_REPOSITORIES = ("PostHog/posthog", "PostHog/ai-gateway")
AUTOMATIC_REVIEW_REPOSITORY = "PostHog/posthog"


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


def _cached_repositories(integration) -> dict[str, dict]:
    cached = integration.repository_cache if isinstance(integration.repository_cache, list) else []
    return {
        str(repository.get("full_name", "")).lower(): repository
        for repository in cached
        if isinstance(repository, dict)
    }


def _account_name(integration) -> str:
    account = (integration.config or {}).get("account") or {}
    return str(account.get("name") or "")


def _seed_integration(integrations: list):
    """The GitHub connection of the PostHog account.

    The connection's account name decides. The repository cache only helps when no account name
    matches, because the cache is empty until someone opens a repository list, and can be stale.
    """
    for integration in integrations:
        if _account_name(integration).lower() == SEEDED_ACCOUNT.lower():
            return integration
    for integration in integrations:
        if any(full_name.lower() in _cached_repositories(integration) for full_name in SEEDED_REPOSITORIES):
            return integration
    return None


def _seed_repository_rows(apps, team_id: int) -> None:
    Integration = apps.get_model("posthog", "Integration")
    ReviewInstallationClaim = apps.get_model("review_hog", "ReviewInstallationClaim")
    ReviewRepository = apps.get_model("review_hog", "ReviewRepository")

    integrations = (
        Integration.objects.filter(team_id=team_id, kind="github")
        .exclude(integration_id=None)
        .exclude(integration_id="")
        .order_by("id")
    )
    integration = _seed_integration(list(integrations))
    if integration is None:
        logger.warning("review_hog_seed_skipped", reason="no_github_integration", team_id=team_id)
        return
    installation_id = integration.integration_id
    ReviewInstallationClaim.objects.get_or_create(
        team_id=team_id, installation_id=installation_id, defaults={"scope": "selected"}
    )
    cached = _cached_repositories(integration)
    for full_name in SEEDED_REPOSITORIES:
        if ReviewRepository.objects.filter(installation_id=installation_id, full_name__iexact=full_name).exists():
            continue
        # Without a cached id the row matches by name, and the first webhook stores the id.
        cached_id = cached.get(full_name.lower(), {}).get("id")
        ReviewRepository.objects.create(
            team_id=team_id,
            installation_id=installation_id,
            github_repo_id=cached_id if isinstance(cached_id, int) else None,
            full_name=full_name,
            selected=True,
        )
    logger.info("review_hog_seeded_repositories", team_id=team_id, installation_id=installation_id)


def _automatic_review_team_id(apps) -> int | None:
    """The project that ran automatic reviews of PostHog/posthog, or None on any other instance.

    Only one project ever ran them, and only automatic reviews set `automatic_reviewed_head_sha`.
    """
    ReviewReport = apps.get_model("review_hog", "ReviewReport")
    return (
        ReviewReport.objects.filter(
            repository__iexact=AUTOMATIC_REVIEW_REPOSITORY, automatic_reviewed_head_sha__isnull=False
        )
        .order_by("-updated_at")
        .values_list("team_id", flat=True)
        .first()
    )


def seed_review_settings(apps, schema_editor):
    copy_settings_into_preferences(apps, schema_editor)

    team_id = _automatic_review_team_id(apps)
    if team_id is None:
        logger.info("review_hog_seed_skipped", reason="no_automatic_review_project")
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
