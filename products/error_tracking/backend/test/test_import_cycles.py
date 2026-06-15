import sys
import subprocess
from pathlib import Path

# The product-level turbo test task runs pytest from the product directory, and
# `python -c` puts cwd on sys.path — the subprocess needs the repo root there to
# find the posthog package.
_REPO_ROOT = Path(__file__).parents[4]

# The skills build (products/posthog_ai/scripts/build_skills.py) imports the query runners
# in a cold interpreter, before anything has touched the error_tracking api package. If a
# runner imports from api.*, that executes api/__init__.py, whose viewsets import the
# runners right back (api/query.py -> ErrorTrackingQueryRunner) and the import blows up
# with "partially initialized module". Pytest cannot reproduce this in-process — by the
# time tests run, the modules are already cached — so boot a clean interpreter and import
# the runners first, like build_skills does.
_COLD_IMPORT = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django
django.setup()
import products.error_tracking.backend.hogql_queries.error_tracking_query_runner
import products.error_tracking.backend.hogql_queries.error_tracking_issue_correlation_query_runner
"""


def test_query_runners_import_in_cold_interpreter() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _COLD_IMPORT],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, f"cold import of error_tracking query runners failed:\n{result.stderr[-2000:]}"
