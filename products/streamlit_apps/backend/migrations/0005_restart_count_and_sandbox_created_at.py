"""Move restart_count from sandbox row to app row, add sandbox.created_at.

Two related changes that must land together because the new lifecycle code
references both:

- restart_count moves to StreamlitApp because the sandbox row is now updated
  in place (rather than deleted+recreated), so the count is no longer scoped
  to a specific sandbox lifecycle.
- sandbox.created_at gives _sync_sandbox_status a stable timestamp for the
  STARTING-timeout check, replacing the misleading app.updated_at proxy.
"""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("streamlit_apps", "0004_seed_streamlit_oauth_app"),
    ]

    operations = [
        migrations.AddField(
            model_name="streamlitapp",
            name="restart_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RemoveField(
            model_name="streamlitappsandbox",
            name="restart_count",
        ),
        migrations.AddField(
            model_name="streamlitappsandbox",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
