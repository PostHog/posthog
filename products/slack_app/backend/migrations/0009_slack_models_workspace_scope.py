from django.db import migrations, models


def backfill_workspace_id_and_dedupe(apps, schema_editor):
    """Populate ``SlackUserProfileCache.slack_workspace_id`` from the linked
    integration's Slack team id, then dedupe both tables down to the keys
    that the new unique constraints (added in this same migration after the
    data step) will enforce.

    Survivor selection — same rule for both tables: take the row most likely
    to be the "live" one, falling back to a stable id ordering when there's no
    clear winner.

    - ``SlackUserProfileCache``: per ``(slack_workspace_id, slack_user_id)``,
      keep the row with the latest ``refreshed_at`` (NULL last — the column
      tracks when we last hit the Slack API and is the right freshness signal);
      tie-break on the latest ``updated_at``, then on id.
    - ``SlackThreadTaskMapping``: per ``(slack_workspace_id, channel,
      thread_ts)``, keep the row with the latest ``updated_at``; tie-break on
      ``created_at`` and id. ``task_run`` linkage on the losers is dropped —
      acceptable because the resolver pins a thread to a single integration,
      so cross-integration duplicates were only ever produced when an
      integration was deleted and recreated in the same workspace + thread.
    """
    SlackUserProfileCache = apps.get_model("slack_app", "SlackUserProfileCache")
    SlackThreadTaskMapping = apps.get_model("slack_app", "SlackThreadTaskMapping")
    Integration = apps.get_model("posthog", "Integration")

    integration_workspace_by_id: dict[int, str] = {}
    for integration_id, slack_workspace_id in Integration.objects.filter(
        id__in=SlackUserProfileCache.objects.values_list("integration_id", flat=True).distinct()
    ).values_list("id", "integration_id"):
        integration_workspace_by_id[integration_id] = slack_workspace_id

    rows_to_update = []
    for row in SlackUserProfileCache.objects.iterator(chunk_size=500):
        workspace = integration_workspace_by_id.get(row.integration_id)
        if workspace is None:
            continue
        row.slack_workspace_id = workspace
        rows_to_update.append(row)
        if len(rows_to_update) >= 500:
            SlackUserProfileCache.objects.bulk_update(rows_to_update, ["slack_workspace_id"])
            rows_to_update.clear()
    if rows_to_update:
        SlackUserProfileCache.objects.bulk_update(rows_to_update, ["slack_workspace_id"])

    # Orphan rows whose integration is already gone (shouldn't exist under the
    # old CASCADE but defensive): we have no way to recover their workspace,
    # so drop them — they can't survive the upcoming NOT NULL.
    SlackUserProfileCache.objects.filter(slack_workspace_id="").delete()

    _dedupe(
        SlackUserProfileCache,
        group_fields=("slack_workspace_id", "slack_user_id"),
        order_by=("-refreshed_at", "-updated_at", "id"),
    )
    _dedupe(
        SlackThreadTaskMapping,
        group_fields=("slack_workspace_id", "channel", "thread_ts"),
        order_by=("-updated_at", "-created_at", "id"),
    )


def _dedupe(model, *, group_fields: tuple[str, ...], order_by: tuple[str, ...]) -> None:
    """Drop all but the first row (per ``order_by``) inside each duplicate
    group identified by ``group_fields``. Postgres ``NULLS LAST`` ordering on
    ``-refreshed_at`` etc. is what we want for freshness — NULL means "we've
    never refreshed", which is the worst possible signal.
    """
    seen: set[tuple] = set()
    losers: list = []
    for row in model.objects.order_by(*order_by).iterator(chunk_size=500):
        key = tuple(getattr(row, f) for f in group_fields)
        if key in seen:
            losers.append(row.pk)
            continue
        seen.add(key)
    if losers:
        model.objects.filter(pk__in=losers).delete()


def noop_reverse(apps, schema_editor):
    """No reverse for the dedupe — deleted duplicates can't be restored."""


class Migration(migrations.Migration):
    dependencies = [
        ("slack_app", "0008_slackthreadtaskmapping_last_forwarded_ts"),
        ("posthog", "1018_migrate_event_definition_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="slackuserprofilecache",
            name="slack_workspace_id",
            # Default + nullable=False on the model end-state, but for the
            # backfill window the column lives as nullable with an empty
            # default so existing rows can be loaded without violating the
            # constraint. The AlterField below the RunPython makes it NOT NULL.
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_workspace_id_and_dedupe, reverse_code=noop_reverse, elidable=False),
        migrations.RemoveConstraint(
            model_name="slackuserprofilecache",
            name="uniq_slack_user_profile_cache_integration_user",
        ),
        migrations.AddConstraint(
            model_name="slackuserprofilecache",
            constraint=models.UniqueConstraint(
                fields=("slack_workspace_id", "slack_user_id"),
                name="uniq_slack_user_profile_cache_workspace_user",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="slackthreadtaskmapping",
            name="uniq_slack_thread_task_mapping",
        ),
        migrations.AddConstraint(
            model_name="slackthreadtaskmapping",
            constraint=models.UniqueConstraint(
                fields=("slack_workspace_id", "channel", "thread_ts"),
                name="uniq_slack_thread_task_mapping",
            ),
        ),
    ]
