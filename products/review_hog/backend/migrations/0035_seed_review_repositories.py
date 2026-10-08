from django.conf import settings
from django.db import migrations

# The repositories the hardcoded allowlists covered: automatic Flash reviews ran only in
# PostHog/posthog, and the label trigger also accepted PostHog/ai-gateway.
AUTOMATIC_REVIEWS_REPOSITORY = "PostHog/posthog"
LABEL_TRIGGER_ONLY_REPOSITORY = "PostHog/ai-gateway"


def seed_review_repositories(apps, schema_editor):
    ReviewUserSettings = apps.get_model("review_hog", "ReviewUserSettings")
    ReviewRepository = apps.get_model("review_hog", "ReviewRepository")
    ReviewUserRepositoryChoice = apps.get_model("review_hog", "ReviewUserRepositoryChoice")
    Team = apps.get_model("posthog", "Team")

    ReviewUserSettings.objects.filter(review_authored_prs=True, default_review_mode="follow").update(
        default_review_mode="flash"
    )

    # Only the first ReviewHog team receives automatic and label-triggered reviews. Other instances
    # leave the setting empty, or name a team that does not exist there.
    if not settings.REVIEWHOG_TEAM_IDS:
        return
    team_id = settings.REVIEWHOG_TEAM_IDS[0]
    if not Team.objects.filter(id=team_id).exists():
        return

    # "Only listed people" with nobody listed reviews exactly the people who chose Flash themselves.
    for full_name in (AUTOMATIC_REVIEWS_REPOSITORY, LABEL_TRIGGER_ONLY_REPOSITORY):
        ReviewRepository.objects.get_or_create(
            team_id=team_id,
            full_name__iexact=full_name,
            defaults={"full_name": full_name, "flash_for": "listed", "exclude_bots": True},
        )

    # A Flash default applies in every added repository, but the old switch only covered
    # PostHog/posthog. An "off" choice for the label-only repository keeps those users unreviewed
    # there until they change it.
    label_only_repository = ReviewRepository.objects.get(
        team_id=team_id, full_name__iexact=LABEL_TRIGGER_ONLY_REPOSITORY
    )
    flash_user_ids = ReviewUserSettings.objects.filter(team_id=team_id, default_review_mode="flash").values_list(
        "user_id", flat=True
    )
    for user_id in flash_user_ids:
        ReviewUserRepositoryChoice.objects.get_or_create(
            team_id=team_id,
            user_id=user_id,
            repository=label_only_repository,
            defaults={"mode": "off"},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("review_hog", "0034_review_repositories"),
    ]

    # Separate from 0034, so the data writes never share a transaction with the schema change.
    # The tables are small: one settings row per user, and at most two repositories.
    operations = [
        migrations.RunPython(seed_review_repositories, migrations.RunPython.noop, elidable=True),
    ]
