from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0009_drop_indexer_choice"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayscanner",
            name="last_seen_session_id",
            field=models.CharField(
                blank=True,
                db_default="",
                default="",
                help_text=(
                    "Keyset tiebreaker; set when the last batch saturated so the next sweep resumes past "
                    "session_end ties."
                ),
                max_length=200,
            ),
        ),
    ]
