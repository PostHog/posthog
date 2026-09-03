# Generated manually - drops the legacy vision action tables.
# Second step after 0086 removed both models from Django state.

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("replay_vision", "0088_remap_scanner_models_gemini_3_8"),
    ]

    # Runs first: the run table's foreign key references the action table.
    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS replay_vision_visionactionrun;",
            reverse_sql="",  # No reverse - the rows are gone with the table.
        ),
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS replay_vision_visionaction;",
            reverse_sql="",
        ),
    ]
