from django.db import migrations
from django.db.models import Q

import structlog

logger = structlog.get_logger(__name__)

BATCH_SIZE = 500


def clean_invalid_multivariate_filters(apps, schema_editor):
    """
    One-time cleanup before strict filters validation ships (#50084):
    null out malformed `filters.multivariate` (not an object, or `variants`
    missing/empty/not a list). These flags already evaluate as boolean, so
    also drop the now-dangling group variant overrides and any payload keys
    other than "true". Includes soft-deleted flags so a restore can't
    resurrect a violation.
    """
    FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")

    # _base_manager: the default manager excludes soft-deleted flags.
    # Deliberately broad (any non-null multivariate): key-transform lookups can't
    # match a non-array `variants` scalar, so the per-row guard below decides.
    candidates = FeatureFlag._base_manager.filter(Q(filters__has_key="multivariate") & ~Q(filters__multivariate=None))

    total = 0
    batch: list = []

    for flag in candidates.iterator(chunk_size=BATCH_SIZE):
        if not isinstance(flag.filters, dict):
            continue

        multivariate = flag.filters.get("multivariate")
        if multivariate is None:
            continue
        variants = multivariate.get("variants") if isinstance(multivariate, dict) else None
        if isinstance(variants, list) and len(variants) > 0:
            continue

        new_filters = {**flag.filters, "multivariate": None}

        # The flag is boolean: no variant overrides can resolve,
        # and only the "true" payload key is meaningful.
        groups = new_filters.get("groups")
        if isinstance(groups, list):
            new_filters["groups"] = [
                {**group, "variant": None} if isinstance(group, dict) and group.get("variant") is not None else group
                for group in groups
            ]
        payloads = new_filters.get("payloads")
        if isinstance(payloads, dict) and any(key != "true" for key in payloads):
            new_filters["payloads"] = {key: value for key, value in payloads.items() if key == "true"}

        flag.filters = new_filters
        batch.append(flag)

        if len(batch) >= BATCH_SIZE:
            FeatureFlag._base_manager.bulk_update(batch, ["filters"])
            total += len(batch)
            batch = []

    if batch:
        FeatureFlag._base_manager.bulk_update(batch, ["filters"])
        total += len(batch)

    logger.info("cleaned_invalid_multivariate_filters", updated_rows=total)


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0006_validate_archived_flag_must_be_disabled"),
    ]

    operations = [
        migrations.RunPython(clean_invalid_multivariate_filters, migrations.RunPython.noop, elidable=True),
    ]
