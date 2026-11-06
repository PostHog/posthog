import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Add team scope to agent grants, plus the audit columns recording which
    member's credential an agent call rode.

    Additive only. Every new column is nullable or carries a Postgres-level
    default, so pods on the previous release keep inserting grants and audit
    rows without them while the deploy rolls.
    """

    dependencies = [
        ("mcp_store", "0025_drop_old_agent_server_access"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpauditevent",
            name="credential_owner",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="mcpauditevent",
            name="grant_scope",
            field=models.CharField(blank=True, db_default="", default="", max_length=20),
        ),
        migrations.AddField(
            model_name="mcpserviceaccountserveraccess",
            name="scope",
            field=models.CharField(
                choices=[("personal", "Personal"), ("team", "Team")],
                db_default="personal",
                default="personal",
                max_length=20,
            ),
        ),
    ]
