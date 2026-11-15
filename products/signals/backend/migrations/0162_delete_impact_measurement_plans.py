from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

BATCH_SIZE = 500


def delete_impact_measurement_plans(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    # The inbound relations to artefacts prevent a fast delete, so Django loads each doomed row before it deletes it.
    # Batches and `only("id")` keep the plan contents out of memory.
    artefact = apps.get_model("signals", "SignalReportArtefact")
    artefacts = artefact.objects.using(schema_editor.connection.alias)
    plans = artefacts.filter(type="impact_measurement_plan").order_by("id")
    cursor = None
    while True:
        page = plans.filter(id__gt=cursor) if cursor else plans
        plan_ids = list(page.values_list("id", flat=True)[:BATCH_SIZE])
        if not plan_ids:
            return
        cursor = plan_ids[-1]
        artefacts.filter(id__in=plan_ids).only("id").delete()


class Migration(migrations.Migration):
    dependencies = [("signals", "0161_add_report_check_approval")]

    operations = [migrations.RunPython(delete_impact_measurement_plans, migrations.RunPython.noop)]
