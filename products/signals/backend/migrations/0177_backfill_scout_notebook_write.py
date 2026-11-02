import json

from django.db import migrations

BATCH_SIZE = 500

NOTEBOOK_WRITE_SCOPE = "notebook:write"

# The MCP tools that required `notebook:write` when this migration was written. Frozen here, because
# what an applied migration did must not change when the live tool catalogue does.
NOTEBOOK_WRITE_TOOLS = frozenset(
    {
        "notebook-edit",
        "notebooks-add-cell",
        "notebooks-configure-compute",
        "notebooks-create",
        "notebooks-create-markdown",
        "notebooks-delete-cell",
        "notebooks-destroy",
        "notebooks-partial-update",
        "notebooks-run",
        "notebooks-run-cell",
        "notebooks-run-cell-interrupt",
        "notebooks-run-status",
        "notebooks-set-variables",
        "notebooks-widget-attach",
        "notebooks-widget-cancel",
        "notebooks-widget-generate",
    }
)


def _with_notebook_write(write_scopes: object, allowed_mcp_tools: object) -> list[str] | None:
    """The grant a config holds once notebooks move into it, or None to leave the row alone.

    A config with a tool list derives its grant from the tools it picked, so it gains notebooks only
    when it picked a notebook write tool. Every other config held notebooks through the fleet posture
    and keeps them. A malformed grant granted nothing at mint time, so it becomes notebooks alone.
    """
    if allowed_mcp_tools is not None:
        picked = isinstance(allowed_mcp_tools, list) and any(tool in NOTEBOOK_WRITE_TOOLS for tool in allowed_mcp_tools)
        if not picked:
            return None
    held = [scope for scope in write_scopes if isinstance(scope, str)] if isinstance(write_scopes, list) else []
    if NOTEBOOK_WRITE_SCOPE in held:
        return None
    return sorted({*held, NOTEBOOK_WRITE_SCOPE})


def grant_notebook_write(apps, schema_editor):
    """Add `notebook:write` to every existing scout's grant, so no scout loses notebooks on deploy."""
    SignalScoutConfig = apps.get_model("signals", "SignalScoutConfig")
    configs = SignalScoutConfig._default_manager.order_by("id")
    cursor = None
    while True:
        page = configs.filter(id__gt=cursor) if cursor else configs
        rows = list(page.values_list("id", "write_scopes", "allowed_mcp_tools")[:BATCH_SIZE])
        if not rows:
            return
        cursor = rows[-1][0]
        # Grouped by the grant read, so a batch costs one UPDATE per distinct grant rather than one
        # per config. Most configs hold the same empty grant.
        ids_by_grant: dict[str, tuple[object, list[str], list]] = {}
        for config_id, write_scopes, allowed_mcp_tools in rows:
            granted = _with_notebook_write(write_scopes, allowed_mcp_tools)
            if granted is None:
                continue
            key = json.dumps(write_scopes, sort_keys=True)
            ids_by_grant.setdefault(key, (write_scopes, granted, []))[2].append(config_id)
        for write_scopes, granted, ids in ids_by_grant.values():
            # `update()`, not `save()`: a backfill must not bump `updated_at` or write an activity
            # log entry nobody made. Matching on the grant read above skips a config a person edited
            # since, so the backfill never overwrites a newer grant.
            SignalScoutConfig._default_manager.filter(id__in=ids, write_scopes=write_scopes).update(
                write_scopes=granted
            )


class Migration(migrations.Migration):
    # Non-atomic so each batch commits as it goes, instead of holding every config locked until the
    # last batch is written. Safe to rerun after a partial run: a row that already holds the scope
    # is skipped.
    atomic = False

    dependencies = [
        ("signals", "0176_signalscoutconfig_default_notebook_write"),
    ]

    operations = [
        # Reverse is a noop: removing the scope would take notebooks away from scouts that held
        # them before this migration, through the fleet posture.
        migrations.RunPython(grant_notebook_write, migrations.RunPython.noop, elidable=True),
    ]
