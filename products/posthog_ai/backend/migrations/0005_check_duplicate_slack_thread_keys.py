from django.db import migrations
from django.db.models import Count


def fail_on_duplicate_slack_thread_keys(apps, schema_editor):
    Conversation = apps.get_model("posthog_ai", "Conversation")
    conflicts = (
        Conversation.objects.filter(slack_thread_key__isnull=False)
        .values("team_id", "slack_thread_key")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
        .order_by()[:20]
    )
    team_ids = sorted({row["team_id"] for row in conflicts})
    if team_ids:
        raise RuntimeError(
            "ee_conversation has duplicate (team_id, slack_thread_key) rows, so the unique index "
            f"unique_team_slack_thread_key cannot be built. Affected teams: {team_ids}. "
            "Remove the duplicate rows, then run this migration again."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog_ai", "0004_conversation_agent_runtime_conversation_task_and_more"),
    ]

    operations = [
        # Stop the deploy here, before migration 0006 spends a full concurrent build
        # on an index that can only fail. A failed unique build leaves another
        # invalid index behind, which is the state 0006 repairs.
        migrations.RunPython(fail_on_duplicate_slack_thread_keys, migrations.RunPython.noop, elidable=True),
    ]
