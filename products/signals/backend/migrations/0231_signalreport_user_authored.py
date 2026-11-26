import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1421_oauth_supports_step_up"),
        ("signals", "0230_monitoring_research_delivery_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="signalreport",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="signalreport",
            name="user_authored",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
