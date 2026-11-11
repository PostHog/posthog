from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("stamphog", "0013_review_on_clean_external_review"),
    ]

    operations = [
        migrations.AlterField(
            model_name="routingrunowner",
            name="reason",
            field=models.CharField(
                choices=[
                    ("sensitive", "Owns a sensitive path"),
                    ("new_path", "Owns a new path"),
                    ("largest_owner", "Has the largest part"),
                    ("diff_not_seen", "Diff not shown to the model"),
                    ("cut_skipped", "Cut step skipped"),
                    ("model_kept", "Kept by the model"),
                    ("model_cut", "Cut by the model"),
                    ("shared_behavior_kept", "Kept by the shared behavior check"),
                    ("shared_behavior_cut", "Cut by the shared behavior check"),
                    ("shared_behavior_no_answer", "Shared behavior check gave no answer"),
                    ("stamphog_approved", "Stamphog approved"),
                ],
                max_length=32,
            ),
        ),
    ]
