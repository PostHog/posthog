import django.utils.timezone
import django.db.models.deletion
from django.db import migrations, models

import posthog.uuidt


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1262_organization_members_can_see_org_members"),
        ("skills", "0008_alter_communityskillvote_user_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="LLMSkillTag",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.uuidt.uuid7,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("skill_name", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "team",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="posthog.team",
                    ),
                ),
            ],
            options={
                "db_table": "llm_analytics_llmskilltag",
                "indexes": [
                    models.Index(fields=["team", "name"], name="llm_skill_tag_team_name_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team", "skill_name", "name"),
                        name="unique_llm_skill_tag",
                    )
                ],
            },
        ),
    ]
