from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0004_alter_content_type"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(fields=["report"], name="signals_sig_report__idx"),
        ),
    ]
