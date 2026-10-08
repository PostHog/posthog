import os
import sys
import subprocess

from django.conf import settings
from django.test import SimpleTestCase

from parameterized import parameterized


class TestImportOrder(SimpleTestCase):
    @parameterized.expand(
        [
            ("prompt_questions", "products.replay_vision.backend.prompt_questions"),
            ("inline_scan", "products.replay_vision.backend.inline_scan"),
            (
                "backfill_command",
                "products.replay_vision.backend.management.commands.backfill_replay_scanner_prompt_questions",
            ),
        ]
    )
    def test_module_imports_before_the_temporal_package(self, _name: str, module: str) -> None:
        # A test process has already loaded the temporal package, so only a fresh interpreter sees the cycle.
        result = subprocess.run(
            [sys.executable, "-c", f"import django; django.setup(); import {module}"],
            cwd=settings.BASE_DIR,
            env={**os.environ, "DJANGO_SETTINGS_MODULE": "posthog.settings"},
            capture_output=True,
            text=True,
            timeout=180,
        )

        assert result.returncode == 0, result.stderr[-2000:]
