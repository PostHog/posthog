from django.db import migrations

BATCH_SIZE = 1000

# An audit entry stores the label the inbox settings show, not the column name, because
# `changes_between` resolves the field through `field_name_overrides` before it writes. The literal
# is frozen here rather than read from that map, so rewording the label cannot change what an
# applied migration matched; the test drives the real settings endpoint to catch the two drifting
# apart. Whole-column containment is also the only form the GIN index on `detail` serves.
LABEL_SWITCH_CHANGE = {"changes": [{"field": "label self-driving PRs"}]}


def _teams_that_chose(apps):
    """Teams whose audit trail records a change to the label switch.

    ActivityLog reaches the migration state through this app's dependency on posthog. A row for
    this scope always carries a team, but the column is nullable for org-scoped rows, so the query
    excludes those rather than putting None in an `IN` clause.
    """
    ActivityLog = apps.get_model("posthog", "ActivityLog")
    return set(
        ActivityLog.objects.filter(
            scope="SignalTeamConfig",
            team_id__isnull=False,
            detail__contains=LABEL_SWITCH_CHANGE,
        ).values_list("team_id", flat=True)
    )


def enable_pull_request_label(apps, schema_editor):
    """Turn the label on for teams that never expressed a choice about it.

    The switch shipped opt-in two days before this migration, so nearly every `false` means the
    team never opened the settings page. Not all of them: a team could turn the label on and then
    off inside that window, and that `false` is a refusal, not an old default. The audit trail
    separates the two cases, so this leaves a team that chose alone and flips the rest. A `false`
    written after this runs is a refusal too, and no later migration touches it.
    """
    SignalTeamConfig = apps.get_model("signals", "SignalTeamConfig")
    pending = (
        SignalTeamConfig.objects.filter(pull_request_label_enabled=False)
        .exclude(team_id__in=_teams_that_chose(apps))
        .order_by("id")
    )
    # One row per team, so the table tracks team count. Page it rather than locking every row
    # until the last one commits.
    cursor = None
    while True:
        page = pending.filter(id__gt=cursor) if cursor else pending
        ids = list(page.values_list("id", flat=True)[:BATCH_SIZE])
        if not ids:
            return
        cursor = ids[-1]
        SignalTeamConfig.objects.filter(id__in=ids).update(pull_request_label_enabled=True)


class Migration(migrations.Migration):
    # Non-atomic so each batch commits and releases its row locks as it goes. Safe to resume after
    # a partial run: a pass only selects rows that still hold the old default.
    atomic = False

    dependencies = [
        ("signals", "0155_alter_signalteamconfig_pull_request_label_enabled"),
    ]

    # Reverse is a noop: turning every row back off would also clear the teams that asked for the
    # label before this ran.
    operations = [
        migrations.RunPython(enable_pull_request_label, migrations.RunPython.noop, elidable=True),
    ]
