from django.db import migrations

from products.signals.backend.suggested_reviewer_index import rebuild_suggested_reviewer_index


def backfill_suggested_reviewer_index(apps, schema_editor):
    """Index the reports whose reviewer artefact was written before the index table existed.

    0150 created the table, and the index is only written when a reviewer artefact changes, so
    every report that already had reviewers came out of that deploy with no rows. Both inbox
    reviewer reads come from the table alone, so those reports report nobody as a suggested
    reviewer and drop out of the scoped lists and counts until their rows exist.

    The walk covers every team, because the gap is in every project. It skips a report that
    already has rows, so it cannot replace a row set the running app wrote, and a retry after a
    partial run picks up only what is left.
    """
    SignalReportArtefact = apps.get_model("signals", "SignalReportArtefact")
    SignalReportSuggestedReviewer = apps.get_model("signals", "SignalReportSuggestedReviewer")
    walk = rebuild_suggested_reviewer_index(
        # The artefact type is a literal, because a migration must keep reading the same rows
        # after the enum member the value came from is renamed or dropped.
        reviewer_artefacts=SignalReportArtefact._default_manager.filter(type="suggested_reviewers"),
        # `_default_manager`, not `objects`: the index model's Meta routes the default manager to
        # the unscoped `all_teams`, so the historical model carries no `objects` attribute.
        index_rows=SignalReportSuggestedReviewer._default_manager.all(),
        only_missing=True,
        # `bin/migrate` migrates over `default_direct`, which bypasses PgBouncer and carries the
        # migration `lock_timeout`. An unbound queryset would leave that connection and route by
        # itself, so the walk would read through the pooler, or from the replica once either model
        # joins `READ_REPLICA_OPT_IN`, while writing to the primary.
        using=schema_editor.connection.alias,
    )
    for written, cursor in walk:
        print(f"Indexed {written} reports; resume after {cursor}")  # noqa: T201


class Migration(migrations.Migration):
    # Each batch of reports commits on its own, so the backfill never holds one transaction open
    # across the whole artefact log. A retry re-reads what is still missing, so a partial run is
    # safe to resume.
    atomic = False

    dependencies = [("signals", "0152_alter_signalscoutsuggestionset_status")]

    operations = [
        migrations.RunPython(backfill_suggested_reviewer_index, migrations.RunPython.noop, elidable=True),
    ]
