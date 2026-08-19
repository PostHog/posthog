from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def _narrow(value: object) -> tuple[object, bool]:
    """Whole floats become ints. Everything else passes through, bools included: they are a
    subclass of int, not float. `is_integer()` is False for NaN and Infinity, so neither reaches
    `int()`."""
    if not isinstance(value, float) or not value.is_integer():
        return value, False
    return int(value), True


def _narrow_rollout_percentages(filters: dict) -> tuple[dict, int]:
    """Idempotent transform re-storing whole rollout percentages as ints.
    Returns (new_filters, narrowed_count); 0 means the flag is untouched."""
    narrowed = 0
    new_filters = dict(filters)

    groups = new_filters.get("groups")
    if isinstance(groups, list):
        new_groups = []
        for group in groups:
            if not isinstance(group, dict):
                new_groups.append(group)
                continue
            new_group = dict(group)
            value, changed = _narrow(new_group.get("rollout_percentage"))
            if changed:
                new_group["rollout_percentage"] = value
                narrowed += 1
            new_groups.append(new_group)
        new_filters["groups"] = new_groups

    multivariate = new_filters.get("multivariate")
    if isinstance(multivariate, dict):
        variants = multivariate.get("variants")
        if isinstance(variants, list):
            new_variants = []
            for variant in variants:
                if not isinstance(variant, dict):
                    new_variants.append(variant)
                    continue
                new_variant = dict(variant)
                value, changed = _narrow(new_variant.get("rollout_percentage"))
                if changed:
                    new_variant["rollout_percentage"] = value
                    narrowed += 1
                new_variants.append(new_variant)
            new_multivariate = dict(multivariate)
            new_multivariate["variants"] = new_variants
            new_filters["multivariate"] = new_multivariate

    holdout = new_filters.get("holdout")
    if isinstance(holdout, dict):
        value, changed = _narrow(holdout.get("exclusion_percentage"))
        if changed:
            new_holdout = dict(holdout)
            new_holdout["exclusion_percentage"] = value
            new_filters["holdout"] = new_holdout
            narrowed += 1

    return new_filters, narrowed


def narrow_whole_rollout_percentages(apps, schema_editor):
    """Re-store whole rollout percentages as ints so the wire format stops breaking SDKs.

    Validation normalization ran every percentage through a float field, so flags saved
    after it shipped store 100.0 where they used to store 100. The filters JSON is served
    verbatim, and the .NET and Java clients type rollout percentages as int, so they reject
    the whole local evaluation payload. Percentages with real decimals stay floats.

    Percentages live in nested arrays that jsonb prefilters can't select cheaply, so this
    scans all flags read-only and writes only the ones that change. Inactive and
    soft-deleted flags included: their filters are blanked in the cached payload today, but
    reactivating one would put the float straight back on the wire.
    """
    FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")

    updated_rows = 0
    narrowed_values = 0

    # Keyset pagination instead of .iterator(): server-side cursors are disabled when
    # migrations run through pgbouncer (DISABLE_SERVER_SIDE_CURSORS), which would make
    # .iterator() buffer the whole table client-side. id-range batches are memory-bounded
    # regardless of how the connection is pooled.
    last_id = 0
    while True:
        # _base_manager: the default manager excludes soft-deleted flags, also inside bulk_update.
        rows = list(
            FeatureFlag._base_manager.filter(id__gt=last_id)
            .exclude(filters=None)
            .order_by("id")
            .only("id", "filters")[:BATCH_SIZE]
        )
        if not rows:
            break
        last_id = rows[-1].id

        to_update = []
        for flag in rows:
            if not isinstance(flag.filters, dict):
                continue
            new_filters, narrowed = _narrow_rollout_percentages(flag.filters)
            if not narrowed:
                continue
            flag.filters = new_filters
            to_update.append(flag)
            narrowed_values += narrowed

        if to_update:
            FeatureFlag._base_manager.bulk_update(to_update, ["filters"])
            updated_rows += len(to_update)

    logger.info(
        "narrowed_whole_rollout_percentages",
        updated_rows=updated_rows,
        narrowed_values=narrowed_values,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0012_teamfeatureflagsconfig_max_feature_flags_override_and_more"),
    ]

    operations = [
        migrations.RunPython(narrow_whole_rollout_percentages, migrations.RunPython.noop, elidable=True),
    ]
