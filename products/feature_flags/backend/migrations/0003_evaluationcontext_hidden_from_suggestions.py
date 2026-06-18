from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0002_migrate_feature_flags_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="evaluationcontext",
            name="hidden_from_suggestions",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
