"""Drop the AllowedStreamlitPackage model and its allowlist plumbing.

requirements.txt support is going away — sandboxes get whatever lives in the
base image. The package allowlist existed only to gate user-supplied install
specifiers, so it has no remaining users.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("streamlit_apps", "0006_drop_viewer_fields"),
    ]

    operations = [
        migrations.DeleteModel(name="AllowedStreamlitPackage"),
    ]
