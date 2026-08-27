from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def hide_notebook_widget_canvases(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    Canvas = apps.get_model("canvas", "Canvas")
    GeneratedWidget = apps.get_model("notebooks", "GeneratedWidget")

    Canvas._base_manager.filter(id__in=GeneratedWidget._base_manager.values("canvas_id")).exclude(
        source_policy="notebook_widget", deleted=True
    ).update(source_policy="notebook_widget", deleted=True)


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0016_canvas_source_policy"),
        ("notebooks", "0017_generatedwidgetversion_prompt_history"),
    ]

    operations = [
        migrations.RunPython(hide_notebook_widget_canvases, reverse_code=migrations.RunPython.noop),
    ]
