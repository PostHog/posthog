import json

from django.db import migrations

RETIRED_MODIFIER = "usePresortedEventsTable"


def _strip_retired_key(value):
    """Recursively drop the retired modifier from a notebook's tiptap content."""
    if isinstance(value, list):
        return [_strip_retired_key(item) for item in value]
    if isinstance(value, dict):
        return {key: _strip_retired_key(item) for key, item in value.items() if key != RETIRED_MODIFIER}
    return value


def remove_presorted_events_modifier(apps, schema_editor):
    """
    Mirror of migration 0999 for notebooks: the deprecated usePresortedEventsTable modifier was
    removed from the query schema, but notebook content persists whole query nodes that still carry
    it, so those queries hard-fail the extra="forbid" backend with a 400 when the notebook loads.

    Query nodes sit at arbitrary depth inside the tiptap content JSON, so we can't reach the key with
    a single jsonb operator. We only touch the few rows that actually contain it.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, content FROM posthog_notebook WHERE content::text LIKE %s",
            [f"%{RETIRED_MODIFIER}%"],
        )
        rows = cursor.fetchall()

        for notebook_id, content in rows:
            if content is None:
                continue
            # Depending on the driver, a jsonb column comes back either already parsed or as text.
            parsed = json.loads(content) if isinstance(content, str) else content
            cleaned = _strip_retired_key(parsed)
            if cleaned != parsed:
                cursor.execute(
                    "UPDATE posthog_notebook SET content = %s WHERE id = %s",
                    [json.dumps(cleaned), notebook_id],
                )


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("notebooks", "0013_notebooknoderun_connection_id_and_more"),
    ]

    operations = [
        migrations.RunPython(
            remove_presorted_events_modifier,
            reverse_noop,
        ),
    ]
