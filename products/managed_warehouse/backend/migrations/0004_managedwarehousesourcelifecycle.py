import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("managed_warehouse", "0003_remove_duckgres_batch_sink_state"),
        ("posthog", "1304_organization_has_active_subscription"),
    ]

    operations = [
        migrations.CreateModel(
            name="ManagedWarehouseSourceLifecycle",
            fields=[
                (
                    "organization",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="managed_warehouse_source_lifecycle",
                        serialize=False,
                        to="posthog.organization",
                        db_constraint=False,
                    ),
                ),
                ("generation", models.PositiveBigIntegerField(default=0)),
                ("desired_active", models.BooleanField(default=True)),
                ("legacy_conversion_generation", models.PositiveBigIntegerField(blank=True, null=True)),
            ],
            options={"db_table": "posthog_managedwarehousesourcelifecycle"},
        ),
    ]
