"""Delete the never-used current_viewers / max_viewers fields.

The "App is busy" gating these fields drove was never wired to a real
counter — current_viewers stayed at 0, so the gate at max_viewers was
unreachable in practice. Removing them lets us delete the busy-state UI
branch and the connect_info 503 path.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("streamlit_apps", "0005_restart_count_and_sandbox_created_at"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="streamlitappsandbox",
            name="current_viewers",
        ),
        migrations.RemoveField(
            model_name="streamlitappsandbox",
            name="max_viewers",
        ),
    ]
