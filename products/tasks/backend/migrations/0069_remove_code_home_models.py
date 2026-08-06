from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0068_loop_creator_backfill"),
    ]

    # State-only removal: the Code Home / workstreams feature is deleted, but the tables
    # (posthog_code_workstream, posthog_code_pr_snapshot, posthog_code_workflow_config)
    # stay in place and get dropped in a follow-up RunSQL migration after a deploy cycle.
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="CodeWorkstream"),
                migrations.DeleteModel(name="CodePrSnapshot"),
                migrations.DeleteModel(name="CodeWorkflowConfig"),
            ],
        ),
    ]
