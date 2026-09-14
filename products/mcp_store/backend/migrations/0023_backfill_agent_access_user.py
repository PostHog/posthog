from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill_agent_access_user(apps, schema_editor):
    """Attribute each agent grant to the owner of its bound credential.

    This is an exact attribution, not a guess: every pre-personal-grant write
    path bound the granter's own personal installation, and installation.user
    is non-nullable. Grants whose credential has since been deleted stay
    unattributed on purpose. They can never mount a credential under per-user
    resolution (fail closed), and inventing an owner for them, for example from
    granted_by, would reinstate a share the person may have ended by deleting
    the connection. Whoever wants the sharing back re-shares, which creates a
    fresh attributed row; the NULL row lingers harmlessly (nulls are distinct
    under the 0024 unique index and every read path excludes them) until the
    SET NOT NULL follow-up deletes whatever is still unattributed after the
    rollout window.
    """
    MCPServiceAccountServerAccess = apps.get_model("mcp_store", "MCPServiceAccountServerAccess")
    MCPServerInstallation = apps.get_model("mcp_store", "MCPServerInstallation")

    MCPServiceAccountServerAccess.objects.filter(user__isnull=True, installation__isnull=False).update(
        user_id=Subquery(MCPServerInstallation.objects.filter(pk=OuterRef("installation_id")).values("user_id")[:1])
    )


class Migration(migrations.Migration):
    dependencies = [
        ("mcp_store", "0022_mcpserviceaccountserveraccess_user"),
    ]

    operations = [
        migrations.RunPython(backfill_agent_access_user, migrations.RunPython.noop),
    ]
