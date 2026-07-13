from django.db import migrations

BATCH_SIZE = 1000

# Snapshot of products/workflows/backend/services/integration_usage.py extraction logic —
# migrations must stay self-contained as live code evolves.
_MAX_CONFIG_DEPTH = 20


def _coerce_integration_id(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _collect_integration_ids(node, ids, depth=0):
    if depth > _MAX_CONFIG_DEPTH:
        return
    if isinstance(node, dict):
        integration_id = _coerce_integration_id(node.get("integrationId"))
        if integration_id is not None:
            ids.add(integration_id)
        for child in node.values():
            _collect_integration_ids(child, ids, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _collect_integration_ids(item, ids, depth + 1)


def _extract_integration_ids(actions, get_template_inputs_schema):
    ids: set[int] = set()
    for action in actions or []:
        if not isinstance(action, dict) or "function" not in (action.get("type") or ""):
            continue
        config = action.get("config") or {}
        _collect_integration_ids(config.get("inputs"), ids)
        # Function actions store integration inputs as bare IDs; only the template's
        # inputs_schema knows which inputs are integration-typed.
        template_id = config.get("template_id")
        if not template_id:
            continue
        inputs = config.get("inputs") or {}
        for schema_item in get_template_inputs_schema(template_id) or []:
            if not isinstance(schema_item, dict) or schema_item.get("type") != "integration":
                continue
            value = (inputs.get(schema_item.get("key")) or {}).get("value")
            if isinstance(value, dict):
                value = value.get("integrationId")
            integration_id = _coerce_integration_id(value)
            if integration_id is not None:
                ids.add(integration_id)
    return ids


def backfill(apps, schema_editor):
    HogFlow = apps.get_model("workflows", "HogFlow")
    HogFlowIntegration = apps.get_model("workflows", "HogFlowIntegration")
    HogFunctionTemplate = apps.get_model("cdp", "HogFunctionTemplate")
    Integration = apps.get_model("posthog", "Integration")

    template_schema_cache = {}

    def get_template_inputs_schema(template_id):
        # Latest sha by created_at, mirroring HogFunctionTemplate.get_template.
        if template_id not in template_schema_cache:
            template = HogFunctionTemplate.objects.filter(template_id=template_id).order_by("-created_at").first()
            template_schema_cache[template_id] = template.inputs_schema if template else None
        return template_schema_cache[template_id]

    pending: list[tuple] = []

    def flush():
        if not pending:
            return
        referenced_ids = {integration_id for _, _, ids in pending for integration_id in ids}
        # Only link integrations that exist in the flow's team — action JSON is user-controlled.
        team_by_integration = dict(Integration.objects.filter(id__in=referenced_ids).values_list("id", "team_id"))
        rows = [
            HogFlowIntegration(hog_flow_id=flow_id, integration_id=integration_id)
            for flow_id, team_id, ids in pending
            for integration_id in ids
            if team_by_integration.get(integration_id) == team_id
        ]
        HogFlowIntegration.objects.bulk_create(rows, batch_size=BATCH_SIZE, ignore_conflicts=True)
        pending.clear()

    flows = (
        HogFlow.objects.exclude(status="archived")
        .values_list("id", "team_id", "actions")
        .iterator(chunk_size=BATCH_SIZE)
    )
    for flow_id, team_id, actions in flows:
        ids = _extract_integration_ids(actions, get_template_inputs_schema)
        if ids:
            pending.append((flow_id, team_id, ids))
        if len(pending) >= BATCH_SIZE:
            flush()
    flush()


def reverse(apps, schema_editor):
    apps.get_model("workflows", "HogFlowIntegration").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workflows", "0009_hogflowintegration"),
        ("cdp", "0001_migrate_cdp_models"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]
