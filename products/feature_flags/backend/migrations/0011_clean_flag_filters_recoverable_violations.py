import json
import math

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500

# Operators written by external tools that have an unambiguous canonical equivalent.
# Unknown operator strings are left untouched: the audit keeps reporting them until
# they are mapped here or fixed by hand.
OPERATOR_TYPO_MAP = {
    "contains": "icontains",
    "matches regex": "regex",
    "does not equal": "is_not",
    "is_in": "exact",
}

# Operators whose value must be a string; plain numbers are stringified (the
# evaluators compare stringified values anyway).
STRING_VALUE_OPERATORS = frozenset({"regex", "not_regex", "icontains", "not_icontains", "gt", "gte", "lt", "lte"})


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-strict JSON constant: {value}")


def _is_strict_json(value: str) -> bool:
    try:
        json.loads(value, parse_constant=_reject_json_constant)
        return True
    except ValueError:
        return False


def _clean_filters(filters: dict) -> tuple[dict, set[str]]:
    """Idempotent transform fixing the recoverable-violation shapes from the #50084 audit.
    Returns (new_filters, rules_applied); empty set means the flag is untouched."""
    rules: set[str] = set()
    new_filters = dict(filters)

    # Payload values that are strings but not strict JSON become JSON-encoded strings.
    # SDKs that parse-with-fallback return the same value either way; strict parsers stop failing.
    payloads = new_filters.get("payloads")
    if isinstance(payloads, dict):
        new_payloads = {}
        for key, value in payloads.items():
            if isinstance(value, str) and not _is_strict_json(value):
                new_payloads[key] = json.dumps(value)
                rules.add("payload_not_json")
            else:
                new_payloads[key] = value
        if "payload_not_json" in rules:
            new_filters["payloads"] = new_payloads

    # Re-apply the 0007 cleanup: malformed multivariate means the flag is boolean.
    # The API still accepts this shape until enforcement ships, so drift reappears.
    multivariate = new_filters.get("multivariate")
    if multivariate is not None:
        variants = multivariate.get("variants") if isinstance(multivariate, dict) else None
        if not isinstance(variants, list) or len(variants) == 0:
            new_filters["multivariate"] = None
            rules.add("multivariate_empty")
            payloads = new_filters.get("payloads")
            if isinstance(payloads, dict) and any(key != "true" for key in payloads):
                new_filters["payloads"] = {key: value for key, value in payloads.items() if key == "true"}

    groups = new_filters.get("groups")
    if isinstance(groups, list):
        variant_keys = {
            variant.get("key")
            for variant in (new_filters.get("multivariate") or {}).get("variants", [])
            if isinstance(variant, dict)
        }
        new_groups = []
        for group in groups:
            if not isinstance(group, dict):
                new_groups.append(group)
                continue
            new_group = dict(group)

            # Numeric-string rollout percentages become floats.
            rollout = new_group.get("rollout_percentage")
            if isinstance(rollout, str):
                try:
                    parsed = float(rollout)
                except ValueError:
                    parsed = None
                if parsed is not None and math.isfinite(parsed) and 0 <= parsed <= 100:
                    new_group["rollout_percentage"] = parsed
                    rules.add("rollout_percentage_string")

            # Variant overrides that reference no existing variant fall back to the
            # computed variant, same as 0007.
            if new_group.get("variant") and new_group["variant"] not in variant_keys:
                new_group["variant"] = None
                rules.add("dangling_variant_override")

            properties = new_group.get("properties")
            if isinstance(properties, list):
                new_properties = []
                for prop in properties:
                    if not isinstance(prop, dict):
                        new_properties.append(prop)
                        continue
                    new_prop = dict(prop)
                    operator = new_prop.get("operator")

                    # in/not_in outside cohorts hard-errors in the Rust matcher;
                    # exact/is_not with the same value is the intended semantics.
                    if operator in ("in", "not_in") and new_prop.get("type") != "cohort":
                        new_prop["operator"] = "exact" if operator == "in" else "is_not"
                        rules.add("in_not_in_non_cohort")
                    elif isinstance(operator, str) and operator in OPERATOR_TYPO_MAP:
                        new_prop["operator"] = OPERATOR_TYPO_MAP[operator]
                        rules.add("operator_typo")

                    if new_prop.get("operator") in STRING_VALUE_OPERATORS:
                        value = new_prop.get("value")
                        if isinstance(value, int | float) and not isinstance(value, bool):
                            new_prop["value"] = str(value)
                            rules.add("non_string_value")

                    new_properties.append(new_prop)
                new_group["properties"] = new_properties
            new_groups.append(new_group)
        new_filters["groups"] = new_groups

    return new_filters, rules


def clean_flag_filters_recoverable_violations(apps, schema_editor):
    """One-time cleanup of the recoverable violations found by audit_flag_filters (#50084).
    Violations live in nested arrays that jsonb prefilters can't select cheaply, so this
    scans all flags read-only and writes only the ~0.2% that change. Soft-deleted flags
    included, so a restore can't resurrect a violation."""
    FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")

    total = 0
    rule_counts: dict[str, int] = {}
    batch: list = []

    # _base_manager: the default manager excludes soft-deleted flags, also inside bulk_update.
    for flag in FeatureFlag._base_manager.exclude(filters=None).only("id", "filters").iterator(chunk_size=BATCH_SIZE):
        if not isinstance(flag.filters, dict):
            continue
        new_filters, rules = _clean_filters(flag.filters)
        if not rules:
            continue
        for rule in rules:
            rule_counts[rule] = rule_counts.get(rule, 0) + 1
        flag.filters = new_filters
        batch.append(flag)

        if len(batch) >= BATCH_SIZE:
            FeatureFlag._base_manager.bulk_update(batch, ["filters"])
            total += len(batch)
            batch = []

    if batch:
        FeatureFlag._base_manager.bulk_update(batch, ["filters"])
        total += len(batch)

    logger.info("cleaned_flag_filters_recoverable_violations", updated_rows=total, **rule_counts)


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0010_remove_featureflag_performed_rollback_and_more"),
    ]

    operations = [
        migrations.RunPython(clean_flag_filters_recoverable_violations, migrations.RunPython.noop, elidable=True),
    ]
