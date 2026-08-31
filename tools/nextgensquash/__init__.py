"""nextgensquash: propose, emit, install, and retire a from-scratch squash of pre-cutoff Django migrations.

Importing the package bootstraps Django; submodules rely on that running first.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "manage.py").exists())))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django  # noqa: E402

django.setup()
