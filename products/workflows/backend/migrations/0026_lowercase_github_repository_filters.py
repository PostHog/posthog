from django.db import migrations
from django.utils import timezone

BATCH_SIZE = 1000

GITHUB_EVENT_RECEIVED_EVENT = "$github_event_received"

# Lowercasing only preserves meaning for an operator that compares the value as a literal string.
# A pattern changes what it matches, or stops compiling, and a presence operator carries the
# operator string rather than a repository name. A missing operator compiles as exact.
LITERAL_REPOSITORY_OPERATORS = frozenset({"exact", "is_not"})


def _lowercased_properties(properties: list, renamed: dict[str, str]) -> list:
    """The properties with every `repository` value lowercased, recording each rewrite in `renamed`."""
    result = []
    for prop in properties:
        if (
            isinstance(prop, dict)
            and prop.get("key") == "repository"
            and (prop.get("operator") or "exact") in LITERAL_REPOSITORY_OPERATORS
        ):
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

    The compiled bytecode is rewritten in place rather than recompiled, touching only the operands
    of a repository condition so a filter on another key that reuses the same string keeps it.
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
        rewritten["bytecode"] = _lowercased_bytecode(bytecode)
    return rewritten


# The operand(s) of a property condition sit right before the field access that reads
# `properties.repository`: `32, <value>` for one value, or `32, <v1>, 32, <v2>, 44, <n>` for a list.
REPOSITORY_FIELD_ACCESS = [32, "repository", 32, "properties", 1, 2]


def _lowercased_bytecode(bytecode: list) -> list:
    result = list(bytecode)
    width = len(REPOSITORY_FIELD_ACCESS)
    for j in range(2, len(result) - width + 1):
        if result[j : j + width] != REPOSITORY_FIELD_ACCESS:
            continue
        if result[j - 2] == 44 and isinstance(result[j - 1], int):
            operands = [j - 1 - 2 * result[j - 1] + 2 * k for k in range(result[j - 1])]
        else:
            operands = [j - 1]
        for i in operands:
            if i > 0 and result[i - 1] == 32 and isinstance(result[i], str):
                result[i] = result[i].lower()
    return result


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

    for row in (
        HogFlow.objects.using(db_alias)
        .filter(trigger__type="internal-event")
        .order_by("pk")
        .values("pk", "updated_at", "trigger", "actions")
        .iterator(chunk_size=BATCH_SIZE)
    ):
        trigger = _lowercased_config(row["trigger"])
        actions = _lowercased_actions(row["actions"])
        if trigger is None and actions is None:
            continue
        # A row saved since the read went through the serializer, which lowercases on its own, so
        # skipping it is correct and the stale snapshot never overwrites that edit. Bumping
        # updated_at makes an editor tab opened before the rewrite fail its stale-write check.
        HogFlow.objects.using(db_alias).filter(pk=row["pk"], updated_at=row["updated_at"]).update(
            trigger=trigger or row["trigger"], actions=actions or row["actions"], updated_at=timezone.now()
        )


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0025_hogflow_email_sending_paused_by"),
    ]

    operations = [
        migrations.RunPython(lowercase_github_repository_filters, migrations.RunPython.noop),
    ]
