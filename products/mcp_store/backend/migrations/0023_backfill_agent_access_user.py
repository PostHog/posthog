from django.db import migrations


def backfill_agent_access_user(apps, schema_editor):
    """Attribute every agent grant to a person.

    The bound credential is the strongest signal: it is a personal
    installation, so its owner is the person whose access the agent rides. When
    the credential has since been deleted (installation is null) the granter is
    the next best attribution. A grant with neither is unattributable and can
    never be mounted under per-user resolution, so it is dropped rather than
    left behind as a row no read path can ever resolve.
    """
    MCPServiceAccountServerAccess = apps.get_model("mcp_store", "MCPServiceAccountServerAccess")

    rows = (
        MCPServiceAccountServerAccess.objects.filter(user__isnull=True)
        .select_related("installation")
        .order_by("id")
        .iterator(chunk_size=500)
    )
    pending: list = []
    unattributable: list = []
    for row in rows:
        owner_id = row.installation.user_id if row.installation is not None else row.granted_by_id
        if owner_id is None:
            unattributable.append(row.id)
            continue
        row.user_id = owner_id
        pending.append(row)
        if len(pending) >= 500:
            MCPServiceAccountServerAccess.objects.bulk_update(pending, ["user"])
            pending = []
        if len(unattributable) >= 500:
            MCPServiceAccountServerAccess.objects.filter(id__in=unattributable).delete()
            unattributable = []
    if pending:
        MCPServiceAccountServerAccess.objects.bulk_update(pending, ["user"])
    if unattributable:
        MCPServiceAccountServerAccess.objects.filter(id__in=unattributable).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0022_mcpserviceaccountserveraccess_user"),
    ]

    operations = [
        migrations.RunPython(backfill_agent_access_user, migrations.RunPython.noop),
    ]
