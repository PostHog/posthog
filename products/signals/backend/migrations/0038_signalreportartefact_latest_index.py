from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False  # Required for AddIndexConcurrently

    dependencies = [
        ("signals", "0037_signalreportartefact_updated_at_and_more"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="signalreportartefact",
            index=models.Index(fields=["report", "type", "-created_at"], name="signals_sig_rpt_type_ct_idx"),
        ),
    ]
