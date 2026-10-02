from django.db import migrations


def delete_unused_repo_configs(apps, schema_editor):
    """Delete the repo configs a sync created and nobody turned on.

    A sync used to create a disabled row for every repository the member could reach. Those rows
    now live in the installation snapshot instead, so the repositories stay available to add. A row
    with a pull request keeps its review history and stays. A placeholder (blank installation) is in
    no snapshot, and a row with a changed review policy holds a choice someone made, so both stay.
    """
    alias = schema_editor.connection.alias
    repo_config_model = apps.get_model("stamphog", "StamphogRepoConfig")
    pull_request_model = apps.get_model("stamphog", "PullRequest")

    used_config_ids = pull_request_model._default_manager.using(alias).values("repo_config_id")
    (
        repo_config_model._default_manager.using(alias)
        .filter(
            enabled=False,
            digest_enabled=False,
            review_mode=repo_config_model._meta.get_field("review_mode").get_default(),
            trigger_label=repo_config_model._meta.get_field("trigger_label").get_default(),
        )
        .exclude(installation_id="")
        .exclude(id__in=used_config_ids)
        .delete()
    )


class Migration(migrations.Migration):
    """Delete never-used repo configs, after 0008 copied their repositories into the snapshots.

    Separate from 0008 so the delete can be reviewed, or dropped, on its own.
    """

    dependencies = [("stamphog", "0008_backfill_installations")]

    operations = [
        migrations.RunPython(delete_unused_repo_configs, migrations.RunPython.noop, elidable=True),
    ]
