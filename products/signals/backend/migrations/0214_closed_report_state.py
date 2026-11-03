from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("signals", "0213_report_inbox_state_cache")]

    operations = [
        migrations.AlterField(
            model_name="signalreport",
            name="status",
            field=models.CharField(
                choices=[
                    ("potential", "Potential"),
                    ("candidate", "Candidate"),
                    ("in_progress", "In Progress"),
                    ("pending_input", "Pending Input"),
                    ("ready", "Ready"),
                    ("monitoring", "Monitoring"),
                    ("resolved", "Resolved"),
                    ("closed", "Closed"),
                    ("failed", "Failed"),
                    ("deleted", "Deleted"),
                    ("suppressed", "Suppressed"),
                ],
                default="potential",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="signalreport",
            name="status_before_suppression",
            field=models.CharField(
                blank=True,
                choices=[
                    ("potential", "Potential"),
                    ("candidate", "Candidate"),
                    ("in_progress", "In Progress"),
                    ("pending_input", "Pending Input"),
                    ("ready", "Ready"),
                    ("monitoring", "Monitoring"),
                    ("resolved", "Resolved"),
                    ("closed", "Closed"),
                    ("failed", "Failed"),
                    ("deleted", "Deleted"),
                    ("suppressed", "Suppressed"),
                ],
                max_length=20,
                null=True,
            ),
        ),
    ]
