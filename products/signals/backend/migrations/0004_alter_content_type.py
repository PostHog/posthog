from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("signals", "0003_alter_signalreport_status_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE signals_signalreportartefact ALTER COLUMN content TYPE text USING convert_from(content, 'UTF8');",
            reverse_sql="ALTER TABLE signals_signalreportartefact ALTER COLUMN content TYPE bytea USING content::bytea;",
            state_operations=[
                migrations.AlterField(
                    model_name="signalreportartefact",
                    name="content",
                    field=models.TextField(),
                ),
            ],
        ),
    ]
