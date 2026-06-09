from django.db import migrations


def backfill_conversion_filters_to_events(apps, schema_editor):
    """
    Move event-based conversion goals out of the wrong slot.

    Before the `conversion.events` slot existed, an event-based conversion goal was stored as an
    object in `conversion.filters` (e.g. {"events": [{"id": "purchase"}], "source": "events"}).
    `conversion.filters` is supposed to be an array of property filters, so the object both crashes
    the property-conversion picker and is invisible to the matcher (which reads `conversion.events`).

    Relocate the object to `conversion.events = [{filters: <object>}]` and clear the property slot.
    Bytecode is intentionally not compiled here (these never had any, so they never fired — this keeps
    the change behaviour-neutral); it is recompiled the next time the workflow is saved.
    """
    HogFlow = apps.get_model("workflows", "HogFlow")

    for flow in HogFlow.objects.filter(conversion__isnull=False).iterator():
        conversion = flow.conversion or {}
        filters = conversion.get("filters")

        # A valid conversion.filters is a list of property filters. The only malformed shape we fix
        # is the event object {"events": [...], "source": "events"} that predates conversion.events.
        # Leave any other shape untouched rather than risk wiping data we don't recognize.
        if not isinstance(filters, dict) or not filters.get("events"):
            continue

        new_conversion = dict(conversion)
        new_conversion["events"] = [*(new_conversion.get("events") or []), {"filters": filters}]
        new_conversion["filters"] = []
        new_conversion["bytecode"] = []

        # .update() avoids bumping updated_at / firing save signals for a backfill.
        HogFlow.objects.filter(pk=flow.pk).update(conversion=new_conversion)


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0008_teamworkflowsconfig"),
    ]

    operations = [
        migrations.RunPython(backfill_conversion_filters_to_events, migrations.RunPython.noop),
    ]
