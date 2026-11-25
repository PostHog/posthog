from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0159_agent_egress_registration_audit"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentegressregistration",
            name="sandbox_id",
            field=models.CharField(max_length=255, null=True),
        ),
    ]
