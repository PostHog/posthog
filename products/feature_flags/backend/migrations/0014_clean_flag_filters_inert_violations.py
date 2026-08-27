from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500

# The only operator a flag-dependency property can carry. Deliberately a frozen copy of the
# constant in filters_validation, since migrations must stay self-contained while app code moves.
FLAG_PROPERTY_OPERATOR = "flag_evaluates_to"


def _variant_keys(filters: dict) -> set[str]:
    variants = (filters.get("multivariate") or {}).get("variants")
    if not isinstance(variants, list):
        return set()
    return {variant.get("key") for variant in variants if isinstance(variant, dict)}


def _clean_filters(filters: dict) -> tuple[dict, set[str]]:
    """Idempotent transform for the #50084 violations that no evaluator can observe.

    Every rule here is a no-op at runtime, so the stored value changes and flag behaviour does
    not. Violations that need a human decision (rollout sums, property types for the condition
    set's aggregation) are deliberately absent. Returns (new_filters, rules_applied); an empty
    set means the flag is untouched."""
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

            # A flag dependency is only ever compared with flag_evaluates_to; the evaluator
            # reads the dependency by type, so the stored operator never changes the outcome.
            properties = new_group.get("properties")
            if isinstance(properties, list):
                new_properties = []
                for prop in properties:
                    if not isinstance(prop, dict):
                        new_properties.append(prop)
                        continue
                    new_prop = dict(prop)
                    if new_prop.get("type") == "flag" and new_prop.get("operator") != FLAG_PROPERTY_OPERATOR:
                        new_prop["operator"] = FLAG_PROPERTY_OPERATOR
                        rules.add("flag_property_requires_flag_evaluates_to")
                    new_properties.append(new_prop)
                new_group["properties"] = new_properties

            new_groups.append(new_group)
        new_filters["groups"] = new_groups

    # Payloads are looked up by the matched variant key, or by "true" on a boolean flag, so a
    # payload under any other key is unreachable and dropping it is invisible.
    payloads = new_filters.get("payloads")
    if isinstance(payloads, dict):
        kept, rule = payloads, ""
        if new_filters.get("multivariate"):
            # Only prune against a variant list we could actually read. With no keys to compare
            # against, every payload would look orphaned; a flag whose variants are missing or
            # malformed belongs to the multivariate_empty rule in 0011, not to this one.
            if variant_keys:
                kept = {key: value for key, value in payloads.items() if key in variant_keys}
                rule = "payload_key_not_a_variant"
        else:
            kept = {key: value for key, value in payloads.items() if key == "true"}
            rule = "payload_key_not_true"
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

    total = 0
    rule_counts: dict[str, int] = {}

    # Keyset pagination instead of .iterator(): server-side cursors are disabled when migrations
    # run through pgbouncer (DISABLE_SERVER_SIDE_CURSORS), which would make .iterator() buffer the
    # whole table client-side. id-range batches are memory-bounded however the connection is pooled.
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
            new_filters, rules = _clean_filters(flag.filters)
            if not rules:
                continue
            for rule in rules:
                rule_counts[rule] = rule_counts.get(rule, 0) + 1
            flag.filters = new_filters
            to_update.append(flag)

        if to_update:
            FeatureFlag._base_manager.bulk_update(to_update, ["filters"])
            total += len(to_update)

    logger.info("cleaned_flag_filters_inert_violations", updated_rows=total, **rule_counts)


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0013_narrow_whole_rollout_percentages"),
    ]

    operations = [
        migrations.RunPython(clean_flag_filters_inert_violations, migrations.RunPython.noop, elidable=True),
    ]
