from django.db import migrations


def backfill_installations(apps, schema_editor):
    """Create one installation record per team and bound installation, from the repo configs.

    Every existing row with an installation was created by a sync, so its repository is one a member
    proved access to. The newest non-null connecting user is the member who proved it last.
    """
    alias = schema_editor.connection.alias
    repo_config_model = apps.get_model("stamphog", "StamphogRepoConfig")
    installation_model = apps.get_model("stamphog", "StamphogInstallation")

    repositories: dict[tuple[int, str, str], set[str]] = {}
    connectors: dict[tuple[int, str, str], int] = {}
    rows = (
        repo_config_model._default_manager.using(alias)
        .exclude(installation_id="")
        .order_by("updated_at")
        .values_list("team_id", "provider", "installation_id", "repository", "connected_by_user_id")
    )
    for team_id, provider, installation_id, repository, connected_by_user_id in rows:
        key = (team_id, provider, installation_id)
        repositories.setdefault(key, set()).add(repository)
        if connected_by_user_id is not None:
            # Rows come oldest first, so the last write is the newest connector.
            connectors[key] = connected_by_user_id

    installation_model._default_manager.using(alias).bulk_create(
        [
            installation_model(
                team_id=team_id,
                provider=provider,
                installation_id=installation_id,
                repositories=sorted(names),
                connected_by_user_id=connectors.get((team_id, provider, installation_id)),
            )
            for (team_id, provider, installation_id), names in repositories.items()
        ],
        # A retried migration finds the records it wrote the first time.
        ignore_conflicts=True,
        batch_size=500,
    )


class Migration(migrations.Migration):
    """Backfill installation records from the repo configs a sync created.

    Separate from 0007 because a data migration in the same file as schema changes is blocked: it
    can hold a lock while those changes wait on it.
    """

    dependencies = [("stamphog", "0007_add_installations")]

    operations = [
        migrations.RunPython(backfill_installations, migrations.RunPython.noop, elidable=True),
    ]
