from django.db import migrations

import structlog

from products.feature_flags.backend.variant_rollout import VARIANT_ROLLOUT_SUM_TOLERANCE

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def _clamped(rollouts: list[float]) -> list[float] | None:
    """Rewrite percentages summing over 100 as what the evaluators already serve, or None.

    Every implementation walks the variants in order accumulating percentages and returns the
    first whose running total passes the hash, which never exceeds 1.0. So a variant starting at
    or beyond 100 is unreachable and one straddling it only serves the remainder: 40/40/40 is
    already 40/40/20. Verified against the Rust server, plus the Python, Go, .NET and JS SDKs.
    Whole numbers stay ints so the wire format keeps the shape #84957 restored."""
    if any(isinstance(r, bool) or not isinstance(r, int | float) for r in rollouts):
        return None
    total = sum(rollouts)
    if total <= 100 + VARIANT_ROLLOUT_SUM_TOLERANCE:
        return None

    clamped: list[float] = []
    used: float = 0
    for rollout in rollouts:
        headroom = 100 - used
        value = rollout if rollout <= headroom else max(headroom, 0)
        if float(value).is_integer():
            value = int(value)
        clamped.append(value)
        used += value
    return clamped


def _clamp_filters(filters: dict) -> dict | None:
    """Idempotent transform; None means the flag is untouched."""
    variants = (
        (filters.get("multivariate") or {}).get("variants") if isinstance(filters.get("multivariate"), dict) else None
    )
    if not isinstance(variants, list) or not variants:
        return None
    if any(not isinstance(variant, dict) for variant in variants):
        return None

    clamped = _clamped([variant.get("rollout_percentage") for variant in variants])
    if clamped is None:
        return None

    new_filters = dict(filters)
    new_multivariate = dict(filters["multivariate"])
    new_multivariate["variants"] = [
        {**variant, "rollout_percentage": value} for variant, value in zip(variants, clamped)
    ]
    new_filters["multivariate"] = new_multivariate
    return new_filters


def clamp_rollout_percentages_over_100(apps, schema_editor):
    """One-time cleanup of multivariate flags whose variant percentages sum over 100 (#50084).

    Only the over-100 case: the evaluators truncate it already, so rewriting it changes nothing
    anyone can observe. A sum under 100 is left alone, because the shortfall is a slice of users
    who match the flag and get no variant, and handing it to someone is the customer's call.

    Percentages live in nested arrays that jsonb prefilters can't select cheaply, so this scans
    all flags read-only and writes only the ones that change. Soft-deleted and inactive flags
    included: their filters are blanked in the cached payload, but restoring or re-enabling a
    flag would put the stored value straight back in play."""
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
            new_filters = _clamp_filters(flag.filters)
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
        "clamped_rollout_percentages_over_100",
        updated_rows=updated_rows,
        skipped_concurrent=skipped_concurrent,
    )


class Migration(migrations.Migration):
    # Non-atomic so each row's UPDATE commits as it goes. The default wrapping transaction would
    # stay open across the whole scan, holding an xmin autovacuum cannot advance past on the table
    # the flags API writes to. Safe to resume: every compare-and-swap is independently correct and
    # the transform is idempotent, so a partial run leaves a consistent table.
    atomic = False

    dependencies = [
        ("feature_flags", "0014_clean_flag_filters_inert_violations"),
    ]

    operations = [
        migrations.RunPython(clamp_rollout_percentages_over_100, migrations.RunPython.noop, elidable=True),
    ]
