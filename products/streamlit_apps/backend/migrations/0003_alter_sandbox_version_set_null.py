import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("streamlit_apps", "0002_seed_allowed_packages"),
    ]

    operations = [
        migrations.AlterField(
            model_name="streamlitappsandbox",
            name="version",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="streamlit_apps.streamlitappversion",
            ),
        ),
    ]
