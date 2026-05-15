from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("surveys", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey",
            name="base_language",
            field=models.CharField(default="en", max_length=20),
        ),
    ]
