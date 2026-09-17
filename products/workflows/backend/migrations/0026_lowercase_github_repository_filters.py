from django.db import migrations

BATCH_SIZE = 1000

GITHUB_EVENT_RECEIVED_EVENT = "$github_event_received"


def _lowercased_properties(properties: list, renamed: dict[str, str]) -> list:
    """The properties with every `repository` value lowercased, recording each rewrite in `renamed`."""
    result = []
    for prop in properties:
        if isinstance(prop, dict) and prop.get("key") == "repository":
            value = prop.get("value")
            values = value if isinstance(value, list) else [value]
            renamed.update({item: item.lower() for item in values if isinstance(item, str) and item != item.lower()})
            lowered = [item.lower() if isinstance(item, str) else item for item in values]
            prop = {**prop, "value": lowered if isinstance(value, list) else lowered[0]}
        result.append(prop)
    return result


def _lowercased_filters(filters: object) -> dict | None:
    """The filters with every `repository` value lowercased, or None when nothing changes.

    The compiler ANDs the conditions on an event entry with the global ones, so a repository
    filter written on the entry decides whether the trigger fires too and needs the same rewrite.

    The compiled bytecode holds the same strings as constants, so they are rewritten too rather
    than recompiled; a value string reused by another filter on the same trigger is rare enough
    to accept.
    """
    if not isinstance(filters, dict):
        return None
    events = filters.get("events")
    if not isinstance(events, list) or not any(
        isinstance(event, dict) and event.get("id") == GITHUB_EVENT_RECEIVED_EVENT for event in events
    ):
        return None
    renamed: dict[str, str] = {}
    rewritten: dict = {**filters}
    properties = filters.get("properties")
    if isinstance(properties, list):
        rewritten["properties"] = _lowercased_properties(properties, renamed)
    rewritten["events"] = [
        {**event, "properties": _lowercased_properties(event["properties"], renamed)}
        if isinstance(event, dict)
        and event.get("id") == GITHUB_EVENT_RECEIVED_EVENT
        and isinstance(event.get("properties"), list)
        else event
        for event in events
    ]
    if not renamed:
        return None
    bytecode = filters.get("bytecode")
    if isinstance(bytecode, list):
        rewritten["bytecode"] = [renamed.get(op, op) if isinstance(op, str) else op for op in bytecode]
    return rewritten


def _lowercased_config(config: object) -> dict | None:
    if not isinstance(config, dict) or config.get("type") != "internal-event":
        return None
    filters = _lowercased_filters(config.get("filters"))
    return None if filters is None else {**config, "filters": filters}


def _lowercased_actions(actions: object) -> list | None:
    if not isinstance(actions, list):
        return None
    changed = False
    result = []
    for action in actions:
        config = (
            _lowercased_config(action.get("config"))
            if isinstance(action, dict) and action.get("type") == "trigger"
            else None
        )
        if config is not None:
            action = {**action, "config": config}
            changed = True
        result.append(action)
    return result if changed else None


def lowercase_github_repository_filters(apps, schema_editor):
    """Publishing a draft or restoring a revision re-runs the serializer, which lowercases on its own,
    so only the live trigger and its action need rewriting here."""
    HogFlow = apps.get_model("workflows", "HogFlow")
    db_alias = schema_editor.connection.alias
    flows_to_update = []

    for row in (
        HogFlow.objects.using(db_alias)
        .filter(trigger__type="internal-event")
        .order_by("pk")
        .values("pk", "trigger", "actions")
        .iterator(chunk_size=BATCH_SIZE)
    ):
        trigger = _lowercased_config(row["trigger"])
        actions = _lowercased_actions(row["actions"])
        if trigger is None and actions is None:
            continue
        flows_to_update.append(
            HogFlow(pk=row["pk"], trigger=trigger or row["trigger"], actions=actions or row["actions"])
        )
        if len(flows_to_update) == BATCH_SIZE:
            HogFlow.objects.using(db_alias).bulk_update(flows_to_update, ["trigger", "actions"], batch_size=BATCH_SIZE)
            flows_to_update = []

    if flows_to_update:
        HogFlow.objects.using(db_alias).bulk_update(flows_to_update, ["trigger", "actions"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0025_hogflow_email_sending_paused_by"),
    ]

    operations = [
        migrations.RunPython(lowercase_github_repository_filters, migrations.RunPython.noop),
    ]
