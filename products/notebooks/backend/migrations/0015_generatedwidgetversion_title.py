from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def reconcile_legacy_widget_versions(apps: Apps, _schema_editor: BaseDatabaseSchemaEditor) -> None:
    Canvas = apps.get_model("canvas", "Canvas")
    GeneratedWidget = apps.get_model("notebooks", "GeneratedWidget")
    GeneratedWidgetVersion = apps.get_model("notebooks", "GeneratedWidgetVersion")
    NotebookWidgetInstance = apps.get_model("notebooks", "NotebookWidgetInstance")

    Canvas._base_manager.filter(id__in=GeneratedWidget._base_manager.values("canvas_id")).update(
        source_policy="notebook_widget", deleted=True
    )

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
    matched_versions = [
        (widget_id, current_version_id)
        for widget_id, canvas_id in widgets
        if (current_version_id := version_ids.get((widget_id, canvas_heads.get(canvas_id)))) is not None
    ]
    for offset in range(0, len(matched_versions), 500):
        batch = matched_versions[offset : offset + 500]
        widget_ids = [widget_id for widget_id, _ in batch]
        widget_version = models.Case(
            *[models.When(id=widget_id, then=models.Value(version_id)) for widget_id, version_id in batch],
            output_field=models.UUIDField(),
        )
        instance_version = models.Case(
            *[models.When(widget_id=widget_id, then=models.Value(version_id)) for widget_id, version_id in batch],
            output_field=models.UUIDField(),
        )
        GeneratedWidget._base_manager.filter(id__in=widget_ids).update(current_version_id=widget_version)
        NotebookWidgetInstance._base_manager.filter(widget_id__in=widget_ids).update(pinned_version_id=instance_version)


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
