"""Replace `unique_together(team, short_id)` with a partial unique constraint.

Soft-deleted apps shouldn't block creating a fresh app with the same short_id
in the same team. Postgres partial unique indexes (UniqueConstraint with a
condition) give us the constraint we want without polluting the active set.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("streamlit_apps", "0007_drop_allowed_packages"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="streamlitapp",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="streamlitapp",
            constraint=models.UniqueConstraint(
                fields=["team", "short_id"],
                condition=models.Q(deleted=False),
                name="streamlit_apps_app_unique_active_short_id_per_team",
            ),
        ),
    ]
