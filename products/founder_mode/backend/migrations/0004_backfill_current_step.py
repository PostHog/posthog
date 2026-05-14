from django.db import migrations


def backfill_current_step(apps, schema_editor):
    FounderProject = apps.get_model("founder_mode", "FounderProject")
    for project in FounderProject.objects.all():
        step = _infer_step(project)
        if step != project.current_step:
            project.current_step = step
            project.save(update_fields=["current_step"])


def _infer_step(project):
    def _has_data(envelope):
        return bool(envelope and envelope.get("status"))

    if _has_data(project.marketing_page) or _has_data(project.marketing_steps):
        return "marketing"
    if _has_data(project.mvp):
        return "mvp"
    if _has_data(project.gtm):
        return "gtm"
    if _has_data(project.validation):
        return "validation"
    return "ideation"


class Migration(migrations.Migration):
    dependencies = [
        ("founder_mode", "0003_founderproject_current_step"),
    ]

    operations = [
        migrations.RunPython(backfill_current_step, migrations.RunPython.noop),
    ]
