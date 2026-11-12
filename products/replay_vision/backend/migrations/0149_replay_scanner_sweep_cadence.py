from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0148_squash_2026_11_02_schema_addons"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayscanner",
            name="sweep_throttle_factor",
            field=models.PositiveSmallIntegerField(
                db_default=1,
                default=1,
                help_text="The frequent sweep's read-budget throttle factor as of the read meter's last run, without the override. Read by the reconciler to pick the sweep schedule's interval.",
            ),
        ),
        migrations.AddField(
            model_name="replayscanner",
            name="last_found_candidates_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When a sweep last found sessions to scan. Scanners that rarely find any are swept less often.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="replayscanner",
            name="sweep_paused_until",
            field=models.DateTimeField(
                blank=True,
                help_text="The sweep schedule is removed until then, because the scanner cannot scan: credit limit reached, experiment not running, or a broken filter. Any save of the scanner clears it.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="replayscanner",
            name="sweep_pause_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("credit_limit", "Credit limit reached"),
                    ("experiment_not_running", "Experiment not running"),
                    ("filter_error", "Filter cannot run"),
                    ("no_principal", "No creator to run the filter as"),
                ],
                db_default="",
                default="",
                help_text="Why the sweep was last paused. Kept past the pause, so the first sweep after it knows whether to skip the paused window.",
                max_length=32,
            ),
        ),
    ]
