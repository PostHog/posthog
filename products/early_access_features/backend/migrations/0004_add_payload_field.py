# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("early_access_features", "0003_fix_contenttype_duplicates"),
    ]

    operations = [
        migrations.AddField(
            model_name="earlyaccessfeature",
            name="payload",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
