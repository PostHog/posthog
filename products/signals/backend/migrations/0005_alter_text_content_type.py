from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0004_rename_content_to_text_content"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE signals_signalreportartefact ALTER COLUMN text_content TYPE text USING convert_from(text_content, 'UTF8');",
            reverse_sql="ALTER TABLE signals_signalreportartefact ALTER COLUMN text_content TYPE bytea USING text_content::bytea;",
            state_operations=[
                migrations.AlterField(
                    model_name="signalreportartefact",
                    name="text_content",
                    field=models.TextField(),
                ),
            ],
        ),
    ]
