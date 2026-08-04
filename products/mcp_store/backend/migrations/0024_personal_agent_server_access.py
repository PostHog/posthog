import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("mcp_store", "0023_backfill_agent_access_user"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mcpserviceaccountserveraccess",
            name="user",
            field=models.ForeignKey(
                db_constraint=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="mcpserviceaccountserveraccess",
            name="uniq_agent_server_access",
        ),
        migrations.AddConstraint(
            model_name="mcpserviceaccountserveraccess",
            constraint=models.UniqueConstraint(
                fields=("service_account", "gateway_server", "user"),
                name="uniq_agent_server_access_per_user",
            ),
        ),
    ]
