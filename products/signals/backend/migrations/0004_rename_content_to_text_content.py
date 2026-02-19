from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0003_alter_signalreport_status_and_more"),
    ]

    operations = [
        migrations.RenameField(
            model_name="signalreportartefact",
            old_name="content",
            new_name="text_content",
        ),
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
        AddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(fields=["report"], name="signals_sig_report__idx"),
        ),
    ]
