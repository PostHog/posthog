from django.db import migrations, models

from posthog.migration_helpers import SafeAddIndexConcurrently


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0236_signalreport_priority_sort_rank_and_more"),
    ]

    operations = [
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(fields=["team", "priority_sort_rank"], name="signals_rpt_team_priority"),
        ),
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                "team", models.F("ranking_open_score").desc(nulls_last=True), name="signals_rpt_team_rank_open"
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                "team", models.F("ranking_action_score").desc(nulls_last=True), name="signals_rpt_team_rank_action"
            ),
        ),
        SafeAddIndexConcurrently(
            model_name="signalreport",
            index=models.Index(
                "team", models.F("ranking_fix_score").desc(nulls_last=True), name="signals_rpt_team_rank_fix"
            ),
        ),
    ]
