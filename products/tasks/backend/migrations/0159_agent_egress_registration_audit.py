from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0158_agent_egress_registration"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentegressregistration",
            name="created_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="agentegressregistration",
            name="revocation_reason",
            field=models.CharField(max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="agentegressregistration",
            name="revoked_at",
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name="agentegressregistration",
            name="revoked_by",
            field=models.CharField(max_length=64, null=True),
        ),
    ]
