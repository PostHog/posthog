from django.db import migrations
from django.db.models import F, Max
from django.db.models.functions import Coalesce, Now

BATCH_SIZE = 500


def stamp_past_suspensions(apps, schema_editor):
    # The trusted floor skips a team with a demotion stamp. Suspensions and AWS pauses from before the
    # floor existed left no stamp, so a reinstated team would otherwise qualify.
    TeamWorkflowsConfig = apps.get_model("workflows", "TeamWorkflowsConfig")
    ActivityLog = apps.get_model("posthog", "ActivityLog")

    candidates = TeamWorkflowsConfig.objects.filter(email_sending_tier_demoted_at__isnull=True)
    candidates.filter(email_sending_suspended_at__isnull=False).update(
        email_sending_tier_demoted_at=F("email_sending_suspended_at")
    )
    team_ids = list(candidates.values_list("team_id", flat=True).order_by("team_id"))
    for start in range(0, len(team_ids), BATCH_SIZE):
        batch = team_ids[start : start + BATCH_SIZE]
        last_suspended = (
            ActivityLog.objects.filter(team_id__in=batch, scope="Team", activity="email_sending_suspended")
            .values("team_id")
            .annotate(at=Max("created_at"))
        )
        for row in last_suspended:
            candidates.filter(team_id=row["team_id"]).update(email_sending_tier_demoted_at=row["at"])

    # A tenant paused now, or REINSTATED after a pause, never moves through the new pause handling, which
    # stamps only on the change to paused.
    candidates.filter(ses_tenant_sending_status__in=["DISABLED", "REINSTATED"]).update(
        email_sending_tier_demoted_at=Coalesce("ses_tenant_state_synced_at", Now())
    )


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0048_teamworkflowsconfig_email_workflow_run_link_tag_enabled"),
        ("posthog", "1406_file_system_team_text_trgm_index"),
    ]

    operations = [migrations.RunPython(stamp_past_suspensions, migrations.RunPython.noop, elidable=True)]
