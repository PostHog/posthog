from __future__ import annotations

import os
import sys
import json
import subprocess
from pathlib import Path


def test_private_database_names_cover_product_aliases() -> None:
    run_id = "0123456789abcdef"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from posthog.settings import data_stores; "
            "print(json.dumps({alias: config.get('TEST', {}) for alias, config in data_stores.DATABASES.items()}))",
        ],
        cwd=Path(__file__).resolve().parents[4],
        env={**os.environ, "TEST": "1", "POSTHOG_TEST_RUN_ID": run_id},
        capture_output=True,
        text=True,
        check=True,
    )
    databases = json.loads(result.stdout.splitlines()[-1])
    assert databases["default"]["NAME"] == f"test_posthog_{run_id}"
    writers = {alias: config for alias, config in databases.items() if alias.endswith("_db_writer")}
    assert writers
    for alias, config in writers.items():
        product = alias.removesuffix("_db_writer")
        assert config["NAME"] == f"test_posthog_{run_id}_{product}"
        assert databases[product + "_db_reader"]["MIRROR"] == alias
