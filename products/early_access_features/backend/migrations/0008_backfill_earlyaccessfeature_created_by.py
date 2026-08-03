# Generated manually

from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill_created_by(apps, schema_editor):
    # Existing features predate creator tracking. The feature flag auto-created alongside each
    # feature was created by the same user in the same request, so its created_by is a reliable
    # best-effort source for the feature's creator.
    EarlyAccessFeature = apps.get_model("early_access_features", "EarlyAccessFeature")
    FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")

    flag_creator = FeatureFlag.objects.filter(id=OuterRef("feature_flag_id")).values("created_by_id")[:1]
    EarlyAccessFeature.objects.filter(created_by__isnull=True, feature_flag__isnull=False).update(
        created_by_id=Subquery(flag_creator)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("early_access_features", "0007_earlyaccessfeature_created_by"),
        ("feature_flags", "0002_migrate_feature_flags_models"),
    ]

    operations = [
        migrations.RunPython(backfill_created_by, migrations.RunPython.noop, elidable=True),
    ]
