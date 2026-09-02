from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def _variant_keys(filters: dict) -> set[str]:
    """Variant keys a stored payload or override could legitimately point at.

    Non-string keys are skipped: a payload key always arrives as a JSON string, so it could
    never resolve to one anyway."""
    multivariate = filters.get("multivariate")
    variants = multivariate.get("variants") if isinstance(multivariate, dict) else None
    if not isinstance(variants, list):
        return set()
    keys = set()
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        key = variant.get("key")
        if isinstance(key, str):
            keys.add(key)
    return keys


# Payload keys the evaluator resolves beyond the variant keys themselves: a boolean result
# looks up "true"/"false", and a user in a holdout gets the synthesised `holdout-{id}` variant.
BOOLEAN_PAYLOAD_KEYS = frozenset({"true", "false"})
HOLDOUT_PAYLOAD_KEY_PREFIX = "holdout-"


def _payload_key_is_resolvable(key: str, variant_keys: set[str]) -> bool:
    # Pinned by test_migration_0014_clean_inert_violations; the holdout and boolean keys are the
    # ones a variant-key-only check silently deletes.
    return key in variant_keys or key in BOOLEAN_PAYLOAD_KEYS or key.startswith(HOLDOUT_PAYLOAD_KEY_PREFIX)


def _clean_filters(filters: dict) -> tuple[dict, set[str]]:
    """Idempotent transform for the #50084 violations that no evaluator can observe.

    Every rule here is a no-op at runtime, so the stored value changes and flag behaviour does
    not. Violations that change what a flag does are deliberately absent: rollout sums, property
    types that don't suit the condition set's aggregation, and flag dependencies carrying the
    wrong operator, which the evaluator treats as an unmatchable condition rather than ignoring.
    Returns (new_filters, rules_applied); an empty set means the flag is untouched."""
    rules: set[str] = set()
    new_filters = dict(filters)
    variant_keys = _variant_keys(new_filters)

    # A variant override the evaluator can't resolve is already ignored: it falls back to the
    # computed variant (get_matching_variant in rust/feature-flags/src/flags/flag_matching.rs).
    groups = new_filters.get("groups")
    if isinstance(groups, list):
        new_groups = []
        for group in groups:
            if not isinstance(group, dict):
                new_groups.append(group)
                continue
            new_group = dict(group)

            variant = new_group.get("variant")
            if variant and variant not in variant_keys:
                new_group["variant"] = None
                rules.add("group_variant_not_a_variant")

            new_groups.append(new_group)
        new_filters["groups"] = new_groups

    # A payload under a key no evaluation can resolve is unreachable, so dropping it is invisible.
    payloads = new_filters.get("payloads")
    if isinstance(payloads, dict):
        if not new_filters.get("multivariate"):
            rule = "payload_key_not_true"
            kept = {k: v for k, v in payloads.items() if _payload_key_is_resolvable(k, set())}
        elif variant_keys:
            rule = "payload_key_not_a_variant"
            kept = {k: v for k, v in payloads.items() if _payload_key_is_resolvable(k, variant_keys)}
        else:
            # No variant list we could read, so every payload would look orphaned. A flag whose
            # variants are missing or malformed belongs to the multivariate_empty rule in 0011.
            rule, kept = "", payloads
        if rule and len(kept) != len(payloads):
            new_filters["payloads"] = kept
            rules.add(rule)

    return new_filters, rules


def clean_flag_filters_inert_violations(apps, schema_editor):
    """One-time cleanup of the #50084 violations that can be repaired without a customer (see
    the per-rule rollout in the issue). Violations live in nested arrays that jsonb prefilters
    can't select cheaply, so this scans all flags read-only and writes only the ones that change.
    Soft-deleted and inactive flags included: their filters are blanked in the cached payload,
    but restoring or re-enabling a flag would put the stored value straight back in play."""
    FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")

    updated_rows = 0
    skipped_concurrent = 0
    rule_counts: dict[str, int] = {}

    # Keyset pagination instead of .iterator(): server-side cursors are disabled when migrations
    # run through pgbouncer (DISABLE_SERVER_SIDE_CURSORS), which would make .iterator() buffer the
    # whole table client-side. id-range batches are memory-bounded however the connection is pooled.
    last_id = 0
    while True:
        # _base_manager documents that soft-deleted rows are in scope (a historical model's
        # manager is plain anyway). Encrypted flags are skipped entirely: every payload key is
        # ciphertext, so dropping one destroys a secret; exclude keeps legacy NULL rows in scope.
        rows = list(
            FeatureFlag._base_manager.filter(id__gt=last_id)
            .exclude(has_encrypted_payloads=True)
            .order_by("id")
            .only("id", "filters")[:BATCH_SIZE]
        )
        if not rows:
            break
        last_id = rows[-1].id

        for flag in rows:
            if not isinstance(flag.filters, dict):
                continue
            new_filters, rules = _clean_filters(flag.filters)
            if not rules:
                continue
            # Compare-and-swap on the value we read: a flag edited between the batch select and
            # this write keeps the newer filters instead of being reverted to our snapshot. Only
            # a few hundred rows change fleet-wide, so per-row writes cost little.
            written = FeatureFlag._base_manager.filter(id=flag.id, filters=flag.filters).update(filters=new_filters)
            if not written:
                skipped_concurrent += 1
                continue
            for rule in rules:
                rule_counts[rule] = rule_counts.get(rule, 0) + 1
            updated_rows += 1

    logger.info(
        "cleaned_flag_filters_inert_violations",
        updated_rows=updated_rows,
        skipped_concurrent=skipped_concurrent,
        **rule_counts,
    )


class Migration(migrations.Migration):
    # Non-atomic so each row's UPDATE commits as it goes. The default wrapping transaction would
    # stay open across the whole scan, holding an xmin autovacuum cannot advance past on the table
    # the flags API writes to. Safe to resume: every compare-and-swap is independently correct and
    # the transform is idempotent, so a partial run leaves a consistent table.
    atomic = False

    dependencies = [
        ("feature_flags", "0013_narrow_whole_rollout_percentages"),
    ]

    operations = [
        migrations.RunPython(clean_flag_filters_inert_violations, migrations.RunPython.noop, elidable=True),
    ]
