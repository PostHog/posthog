from django.db import migrations

BATCH_SIZE = 1000

LEGACY_TRIGGER_TYPE = "slack-message"
INTERNAL_EVENT_TRIGGER_TYPE = "internal-event"
SLACK_MESSAGE_RECEIVED_EVENT = "$slack_message_received"


def _upgraded(config: object) -> dict | None:
    if not isinstance(config, dict) or config.get("type") != LEGACY_TRIGGER_TYPE:
        return None
    filters = config.get("filters")
    filters = dict(filters) if isinstance(filters, dict) else {}
    filters["source"] = "internal-events"
    filters["events"] = [{"id": SLACK_MESSAGE_RECEIVED_EVENT, "type": "events"}]
    return {**config, "type": INTERNAL_EVENT_TRIGGER_TYPE, "filters": filters}


def set_internal_event_triggers(apps, schema_editor):
    HogFlow = apps.get_model("workflows", "HogFlow")
    db_alias = schema_editor.connection.alias
    flows_to_update = []

    for row in (
        HogFlow.objects.using(db_alias)
        .filter(trigger__type=LEGACY_TRIGGER_TYPE)
        .order_by("pk")
        .values("pk", "trigger", "actions")
        .iterator(chunk_size=BATCH_SIZE)
    ):
        trigger = _upgraded(row["trigger"])
        if trigger is None:
            continue

        # The trigger column is derived from the workflow's single trigger action, so both hold the
        # legacy type and both have to move together.
        actions = row["actions"]
        if isinstance(actions, list):
            actions = [
                {**action, "config": _upgraded(action.get("config")) or action.get("config")}
                if isinstance(action, dict) and action.get("type") == "trigger"
                else action
                for action in actions
            ]

        flows_to_update.append(HogFlow(pk=row["pk"], trigger=trigger, actions=actions))
        if len(flows_to_update) == BATCH_SIZE:
            HogFlow.objects.using(db_alias).bulk_update(flows_to_update, ["trigger", "actions"], batch_size=BATCH_SIZE)
            flows_to_update = []

    if flows_to_update:
        HogFlow.objects.using(db_alias).bulk_update(flows_to_update, ["trigger", "actions"], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0020_teamworkflowsconfig_email_sending_tier_and_more"),
    ]

    operations = [
        migrations.RunPython(set_internal_event_triggers, migrations.RunPython.noop),
    ]
