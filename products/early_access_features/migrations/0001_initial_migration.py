# Generated by Django 4.2.15 on 2024-12-06 14:43

from django.db import migrations, models
import posthog.models.utils


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("posthog", "0547_migrate_early_access_features"),
    ]

    database_operations = []

    state_operations = [
        migrations.CreateModel(
            name="EarlyAccessFeature",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("draft", "draft"),
                            ("concept", "concept"),
                            ("alpha", "alpha"),
                            ("beta", "beta"),
                            ("general-availability", "general availability"),
                            ("archived", "archived"),
                        ],
                        max_length=40,
                    ),
                ),
                ("documentation_url", models.URLField(blank=True, max_length=800)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": '"posthog_earlyaccessfeature"',
                "managed": False,
            },
        ),
        migrations.AddField(
            model_name="earlyaccessfeature",
            name="feature_flag",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.PROTECT,
                related_name="features",
                related_query_name="feature",
                to="posthog.featureflag",
            ),
        ),
        migrations.AddField(
            model_name="earlyaccessfeature",
            name="team",
            field=models.ForeignKey(
                default=None,
                on_delete=models.deletion.CASCADE,
                related_name="features",
                related_query_name="feature",
                to="posthog.team",
            ),
            preserve_default=False,
        ),
        migrations.AlterModelOptions(
            name="earlyaccessfeature",
            options={},
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(database_operations=database_operations, state_operations=state_operations)
    ]
