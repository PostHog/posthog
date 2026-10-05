from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0029_seal_reverse_accessors"),
    ]

    operations = [
        migrations.CreateModel(
            name="SandboxSenderTenantState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tenant_name", models.CharField(max_length=64, unique=True)),
                ("sending_status", models.CharField(blank=True, db_default="", default="", max_length=32)),
                ("reputation_impact", models.CharField(blank=True, db_default="", default="", max_length=32)),
                ("synced_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
    ]
