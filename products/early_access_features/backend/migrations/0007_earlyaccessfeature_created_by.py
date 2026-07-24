# Generated manually

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("early_access_features", "0006_migrate_feature_flags_models"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="earlyaccessfeature",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                # db_constraint disabled to avoid locking the hot posthog_user table when adding this FK.
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="early_access_features",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
