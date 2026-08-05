from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("experiments", "0021_alter_experimentmetricsrecalculation_trigger"),
    ]

    operations = [
        migrations.AddField(
            model_name="experiment",
            name="feature_flag_auto_archived",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
