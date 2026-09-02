"""nextgensquash: propose, emit, install, and retire a from-scratch squash of pre-cutoff Django migrations.

Importing the package bootstraps Django; submodules rely on that running first.
"""

import os
import sys
from pathlib import Path

_repo_root = next((p for p in Path(__file__).resolve().parents if (p / "manage.py").exists()), None)
if _repo_root is None:
    raise RuntimeError("nextgensquash must run from inside a PostHog checkout (no manage.py found above the package)")
sys.path.insert(0, str(_repo_root))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django  # noqa: E402

django.setup()
