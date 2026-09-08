import django.db.models.deletion
from django.db import migrations, models

from posthog.migration_helpers import DropIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index drops cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("tasks", "0121_squash_2026_09_07_finalize_fks"),
    ]

    operations = [
        # Django's automatic ForeignKey indexes, neither of which serves a read.
        # `posthog_san_team_id_817c0d_idx` on (team, created_by) leads with team_id, so it
        # already covers every team-scoped lookup. custom_image_id is only filtered by the
        # SET_NULL cascade Django emits when a SandboxCustomImage row is deleted, which is
        # a seq scan this small table can absorb.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="sandboxenvironment",
                    name="team",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="posthog.team",
                    ),
                ),
                migrations.AlterField(
                    model_name="sandboxenvironment",
                    name="custom_image",
                    field=models.ForeignKey(
                        blank=True,
                        db_index=False,
                        help_text="Custom base image for this environment's sandboxes (Modal VM runtime only)",
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="tasks.sandboxcustomimage",
                    ),
                ),
            ],
            database_operations=[
                DropIndexConcurrently(
                    index_name="posthog_sandbox_environment_team_id_d94b6a9a",
                    table_name="posthog_sandbox_environment",
                    columns="(team_id)",
                ),
                DropIndexConcurrently(
                    index_name="posthog_sandbox_environment_custom_image_id_a62b5702",
                    table_name="posthog_sandbox_environment",
                    columns="(custom_image_id)",
                ),
            ],
        ),
    ]
