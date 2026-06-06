# Generated manually

from django.db import migrations


def clear_concept_super_groups(apps, schema_editor):
    """
    Clear super_groups from feature flags linked to CONCEPT-stage early access features.

    Previously, CONCEPT stage features had super_groups enabled, meaning opted-in users
    would immediately have the feature flag enabled. This was counterintuitive since
    CONCEPT is meant for gauging interest before releasing functionality.

    Now only ALPHA, BETA, and GA stages enable the feature flag for opted-in users.
    """
    EarlyAccessFeature = apps.get_model("early_access_features", "EarlyAccessFeature")

    concept_features = EarlyAccessFeature.objects.filter(stage="concept").select_related("feature_flag")

    for eaf in concept_features:
        if eaf.feature_flag and eaf.feature_flag.filters.get("super_groups"):
            eaf.feature_flag.filters = {**eaf.feature_flag.filters, "super_groups": None}
            eaf.feature_flag.save(update_fields=["filters"])


def restore_concept_super_groups(apps, schema_editor):
    """
    Reverse migration: re-add super_groups to CONCEPT-stage features.
    """
    EarlyAccessFeature = apps.get_model("early_access_features", "EarlyAccessFeature")

    concept_features = EarlyAccessFeature.objects.filter(stage="concept").select_related("feature_flag")

    for eaf in concept_features:
        if eaf.feature_flag:
            feature_flag_key = eaf.feature_flag.key
            super_groups = [
                {
                    "properties": [
                        {
                            "key": f"$feature_enrollment/{feature_flag_key}",
                            "type": "person",
                            "operator": "exact",
                            "value": ["true"],
                        },
                    ],
                    "rollout_percentage": 100,
                },
            ]
            eaf.feature_flag.filters = {**eaf.feature_flag.filters, "super_groups": super_groups}
            eaf.feature_flag.save(update_fields=["filters"])


class Migration(migrations.Migration):
    dependencies = [
        ("early_access_features", "0004_add_payload_field"),
        ("posthog", "1030_add_last_calculation_duration_ms"),
    ]

    operations = [
        migrations.RunPython(clear_concept_super_groups, restore_concept_super_groups),
    ]
