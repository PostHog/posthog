from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps


def delete_impact_measurement_plans(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    artefact = apps.get_model("signals", "SignalReportArtefact")
    artefact.objects.using(schema_editor.connection.alias).filter(type="impact_measurement_plan").delete()


class Migration(migrations.Migration):
    dependencies = [("signals", "0161_add_report_check_approval")]

    operations = [migrations.RunPython(delete_impact_measurement_plans, migrations.RunPython.noop)]
