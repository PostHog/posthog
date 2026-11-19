import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from .replay import main  # noqa: E402 — must follow django.setup()

if __name__ == "__main__":
    sys.exit(main())
