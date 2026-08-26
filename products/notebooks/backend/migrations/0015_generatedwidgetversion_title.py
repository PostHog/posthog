from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def reconcile_legacy_widget_versions(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    Canvas = apps.get_model("canvas", "Canvas")
    GeneratedWidget = apps.get_model("notebooks", "GeneratedWidget")
    GeneratedWidgetVersion = apps.get_model("notebooks", "GeneratedWidgetVersion")
    NotebookWidgetInstance = apps.get_model("notebooks", "NotebookWidgetInstance")

    widgets = list(GeneratedWidget._base_manager.filter(generation_jobs__isnull=True).values_list("id", "canvas_id"))
    canvas_heads = dict(
        Canvas._base_manager.filter(id__in=[canvas_id for _, canvas_id in widgets]).values_list(
            "id", "current_source_version_id"
        )
    )
    version_ids = {
        (widget_id, canvas_source_version_id): version_id
        for widget_id, canvas_source_version_id, version_id in GeneratedWidgetVersion._base_manager.filter(
            widget_id__in=[widget_id for widget_id, _ in widgets],
            canvas_source_version_id__in=[version_id for version_id in canvas_heads.values() if version_id is not None],
        ).values_list("widget_id", "canvas_source_version_id", "id")
    }
    for widget_id, canvas_id in widgets:
        current_version_id = version_ids.get((widget_id, canvas_heads.get(canvas_id)))
        if current_version_id is None:
            continue
        GeneratedWidget._base_manager.filter(id=widget_id).update(current_version_id=current_version_id)
        NotebookWidgetInstance._base_manager.filter(widget_id=widget_id).update(pinned_version_id=current_version_id)


class Migration(migrations.Migration):
    dependencies = [
        ("canvas", "0016_canvas_source_policy"),
        ("notebooks", "0014_generatedwidgets"),
    ]

    operations = [
        migrations.AddField(
            model_name="generatedwidgetversion",
            name="title",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.RunPython(reconcile_legacy_widget_versions, reverse_code=migrations.RunPython.noop),
    ]
