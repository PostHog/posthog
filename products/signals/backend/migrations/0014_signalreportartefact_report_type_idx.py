from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("signals", "0013_signalreport_suggested_reviewers"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(fields=["report", "type"], name="signals_sig_report_type_idx"),
        ),
    ]
