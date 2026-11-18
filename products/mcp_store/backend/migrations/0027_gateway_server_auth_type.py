from django.db import migrations, models


class Migration(migrations.Migration):
    """Record how members authenticate to a custom gateway server.

    Additive: the column carries a Postgres-level default, so pods on the
    previous release keep inserting rows without it while the deploy rolls.
    The backfill lives in 0028 so this ALTER's lock commits before it runs.
    """

    dependencies = [
        ("mcp_store", "0026_agent_grant_scope"),
    ]

    operations = [
        migrations.AddField(
            model_name="mcpgatewayserver",
            name="auth_type",
            field=models.CharField(
                blank=True,
                choices=[("api_key", "API Key"), ("oauth", "OAuth")],
                db_default="",
                default="",
                max_length=20,
            ),
        ),
    ]
