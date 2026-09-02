# Generated manually

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("early_access_features", "0008_backfill_earlyaccessfeature_created_by"),
        ("ee", "0028_alter_conversation_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="earlyaccessfeature",
            name="assigned_user",
            field=models.ForeignKey(
                blank=True,
                # db_constraint disabled to avoid locking the hot posthog_user table when adding this FK.
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="earlyaccessfeature",
            name="assigned_role",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="ee.role",
            ),
        ),
    ]
