import os
import sys
import subprocess
from collections.abc import Generator

import pytest

# Runs in a clean interpreter — the pytest process imports the google-ads SDK itself (via the
# google_ads test modules), so we can't inspect this process's sys.modules.
_SDK_LEAK_CHECK = """
import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
SourceRegistry._ensure_loaded()
print("\\n".join(sorted(m for m in sys.modules if m.startswith("google.ads"))))
"""

_LEAK_TEST_NAME = "test_source_registration_does_not_import_google_ads_sdk"


class SdkLeakCheck:
    """Handle for the leak-check subprocess; caches the result so reruns see the same outcome."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self._result: tuple[int, str, str] | None = None

    def result(self, timeout: float) -> tuple[int, str, str]:
        if self._result is None:
            stdout, stderr = self._proc.communicate(timeout=timeout)
            self._result = (self._proc.returncode, stdout, stderr)
        return self._result


@pytest.fixture(scope="session", autouse=True)
def google_ads_sdk_leak_check(request: pytest.FixtureRequest) -> Generator[SdkLeakCheck | None]:
    """Start the SDK-leak-check subprocess at session start so its ~15s of interpreter boot
    (django.setup + full source registry import) overlaps the rest of the suite instead of
    blocking the test that asserts on it. Only launched when that test is actually selected
    (it may live in a different shard).

    Hand the child our import paths so `import posthog` / `products.*` resolves regardless of
    the working directory (the product test job runs pytest from products/warehouse_sources/,
    not the repo root, so a bare `python -c` wouldn't find the repo packages on cwd alone).
    """
    if not any(item.name.startswith(_LEAK_TEST_NAME) for item in request.session.items):
        yield None
        return

    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    proc = subprocess.Popen(
        [sys.executable, "-c", _SDK_LEAK_CHECK],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    yield SdkLeakCheck(proc)
    if proc.poll() is None:
        proc.kill()
