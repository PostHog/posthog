from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("feature_flags", "0003_evaluationcontext_hidden_from_suggestions"),
    ]

    operations = [
        migrations.AddField(
            model_name="featureflag",
            name="archived",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
