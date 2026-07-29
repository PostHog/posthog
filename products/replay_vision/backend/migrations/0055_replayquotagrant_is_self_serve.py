from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0054_revert_remapped_preview_scanners"),
    ]

    operations = [
        migrations.AddField(
            model_name="replayquotagrant",
            name="is_self_serve",
            field=models.BooleanField(
                db_default=False,
                default=False,
                help_text=(
                    "Raised by an organization admin rather than by staff. There is at most one of these per "
                    "organization per period; it grows in steps up to a ceiling."
                ),
            ),
        ),
    ]
