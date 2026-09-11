from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500

# Frozen copy of the operators filters_validation.py requires a string value for, narrowed to
# the numeric comparisons. Migrations must stay self-contained, so a later edit to that set
# cannot change what this one already did.
NUMERIC_COMPARISON_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})


def _stringified_value(value):
    """The stored value as a string, or None when the property needs no change.

    Booleans are excluded because `bool` is a subclass of `int`: "True" is not a number, so
    writing it would turn a comparison that fails today into one that fails differently.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return repr(value) if isinstance(value, float) else str(value)


def _stringify_filters(filters: dict) -> dict | None:
    """Rewrite numeric comparison values as strings, or None when nothing changes.

    The Rust evaluator and the Python SDK parse either form to the same float, so this is a
    no-op for them. The .NET SDK reads a JSON number through its cohort-id constructor, which
    leaves the value it compares against unset, and every gt/gte/lt/lte then matches
    regardless of the person's property. A string restores the comparison there.
    """
    groups = filters.get("groups")
    if not isinstance(groups, list):
        return None

    changed = False
    new_groups = []
    for group in groups:
        if not isinstance(group, dict):
            new_groups.append(group)
            continue
        properties = group.get("properties")
        if not isinstance(properties, list):
            new_groups.append(group)
            continue

        new_properties = []
        for prop in properties:
            if not isinstance(prop, dict) or prop.get("operator") not in NUMERIC_COMPARISON_OPERATORS:
                new_properties.append(prop)
                continue
            as_string = _stringified_value(prop.get("value"))
            if as_string is None:
                new_properties.append(prop)
                continue
            new_properties.append({**prop, "value": as_string})
            changed = True

        new_group = dict(group)
        new_group["properties"] = new_properties
        new_groups.append(new_group)

    if not changed:
        return None
    new_filters = dict(filters)
    new_filters["groups"] = new_groups
    return new_filters


def stringify_numeric_comparison_values(apps, schema_editor):
    """One-time fix for #50084's operator_requires_string_value rule on gt/gte/lt/lte.

    Only the numeric comparisons are in scope. The same rule covers icontains and regex, where
    the stored value is a list rather than a number, and picking one entry from a list changes
    who the flag targets. That belongs with the flag's owner, not here.

    Property values live in nested arrays that jsonb prefilters can't select cheaply, so this
    scans all flags read-only and writes only the ones that change. Soft-deleted and inactive
    flags included: their filters are blanked in the cached payload, but restoring or
    re-enabling a flag would put the stored value straight back in play.
    """
    FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")

    updated_rows = 0
    skipped_concurrent = 0

    # Keyset pagination instead of .iterator(): server-side cursors are disabled when migrations
    # run through pgbouncer (DISABLE_SERVER_SIDE_CURSORS), which would make .iterator() buffer the
    # whole table client-side. id-range batches are memory-bounded however the connection is pooled.
    last_id = 0
    while True:
        # _base_manager documents that soft-deleted rows are in scope (a historical model's
        # manager is plain anyway). Nothing here touches payloads, so encrypted flags are in scope.
        rows = list(FeatureFlag._base_manager.filter(id__gt=last_id).order_by("id").only("id", "filters")[:BATCH_SIZE])
        if not rows:
            break
        last_id = rows[-1].id

        for flag in rows:
            if not isinstance(flag.filters, dict):
                continue
            new_filters = _stringify_filters(flag.filters)
            if new_filters is None:
                continue
            # Compare-and-swap on the value we read: a flag edited between the batch select and
            # this write keeps the newer filters instead of being reverted to our snapshot.
            written = FeatureFlag._base_manager.filter(id=flag.id, filters=flag.filters).update(filters=new_filters)
            if not written:
                skipped_concurrent += 1
                continue
            updated_rows += 1

    logger.info(
        "stringified_numeric_comparison_values",
        updated_rows=updated_rows,
        skipped_concurrent=skipped_concurrent,
    )


class Migration(migrations.Migration):
    # Non-atomic so each row's UPDATE commits as it goes. The default wrapping transaction would
    # stay open across the whole scan, holding an xmin autovacuum cannot advance past on the table
    # the flags API writes to. Safe to resume: every compare-and-swap is independently correct and
    # the transform is idempotent, since a value already stored as a string is skipped.
    atomic = False

    dependencies = [
        ("feature_flags", "0020_alter_featureflag_created_by_alter_featureflag_team_and_more"),
    ]

    operations = [
        migrations.RunPython(stringify_numeric_comparison_values, migrations.RunPython.noop, elidable=True),
    ]
