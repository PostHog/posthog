from django.db import migrations, models

from posthog.migration_helpers import AddConstraintNotValid


class Migration(migrations.Migration):
    dependencies = [
        ("error_tracking", "0045_errortrackingissuesummary"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="errortrackingissuechange",
            name="et_issue_change_actor_matches_type",
        ),
        migrations.AlterField(
            model_name="errortrackingissuechange",
            name="actor_type",
            field=models.TextField(
                choices=[
                    ("ingestion", "Ingestion"),
                    ("user", "User"),
                    ("automation", "Automation"),
                    ("system", "System"),
                ]
            ),
        ),
        AddConstraintNotValid(
            model_name="errortrackingissuechange",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("actor_automation_id__isnull", True),
                        ("actor_type", "ingestion"),
                        ("actor_user_id__isnull", True),
                    ),
                    models.Q(
                        ("actor_automation_id__isnull", True),
                        ("actor_type", "user"),
                        ("actor_user_id__isnull", False),
                    ),
                    models.Q(
                        ("actor_automation_id__isnull", False),
                        ("actor_type", "automation"),
                        ("actor_user_id__isnull", True),
                    ),
                    models.Q(
                        ("actor_automation_id__isnull", True),
                        ("actor_type", "system"),
                        ("actor_user_id__isnull", True),
                    ),
                    _connector="OR",
                ),
                name="et_issue_change_actor_matches_type",
            ),
        ),
    ]
