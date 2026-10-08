from django.conf import settings
from django.db import migrations

# The repositories the hardcoded allowlists covered: automatic Flash reviews ran only in
# PostHog/posthog, and the label trigger also accepted PostHog/ai-gateway. Both become added
# repositories, so a Flash default now also applies in PostHog/ai-gateway.
AUTOMATIC_REVIEWS_REPOSITORY = "PostHog/posthog"
LABEL_TRIGGER_ONLY_REPOSITORY = "PostHog/ai-gateway"


def seed_review_repositories(apps, schema_editor):
    ReviewUserSettings = apps.get_model("review_hog", "ReviewUserSettings")
    ReviewRepository = apps.get_model("review_hog", "ReviewRepository")
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


class Migration(migrations.Migration):
    dependencies = [
        ("review_hog", "0034_review_repositories"),
    ]

    # Separate from 0034, so the data writes never share a transaction with the schema change.
    # The tables are small: one settings row per user, and at most two repositories.
    operations = [
        migrations.RunPython(seed_review_repositories, migrations.RunPython.noop, elidable=True),
    ]
