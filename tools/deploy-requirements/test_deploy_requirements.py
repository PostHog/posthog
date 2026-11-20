import json
import hashlib
import tempfile
import subprocess
from pathlib import Path

import pytest

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SCHEMA = json.loads((HERE / "deploy-requirements.v1.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)
RUST_WRITER = REPO_ROOT / "rust/bin/write-deploy-requirements"


def digest_of(requirements: list[dict]) -> str:
    return hashlib.sha256(json.dumps(requirements, separators=(",", ":")).encode()).hexdigest()[:12]


def errors_of(manifest: dict) -> list[str]:
    return [error.message for error in VALIDATOR.iter_errors(manifest)]


def run_rust_writer(databases: str, migrations_base: Path, output: Path) -> dict:
    subprocess.run(["sh", str(RUST_WRITER), databases, str(output), str(migrations_base)], check=True)
    return json.loads(output.read_text())


class TestSchema:
    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(SCHEMA)

    @pytest.mark.parametrize("example", sorted((HERE / "examples").glob("*.json")), ids=lambda path: path.name)
    def test_examples_match_schema_and_digest(self, example: Path) -> None:
        manifest = json.loads(example.read_text())

        assert errors_of(manifest) == []
        assert manifest["digest"] == digest_of(manifest["requirements"])

    @pytest.mark.parametrize(
        "change",
        [
            {"schema_version": 2},
            {"requirements": [{"kind": "assets", "database": "persons", "versions": [1]}]},
            {"requirements": [{"kind": "sqlx", "database": "persons", "versions": []}]},
            {"requirements": [{"kind": "sqlx", "database": "persons", "versions": ["20250101000001"]}]},
            {"requirements": [{"kind": "sqlx", "database": "unknown", "versions": [1]}]},
            {"digest": "not-hex"},
            {"extra": True},
        ],
        ids=[
            "unknown version",
            "unknown kind",
            "no versions",
            "version as string",
            "unknown sqlx database",
            "bad digest",
            "unknown top-level key",
        ],
    )
    def test_schema_rejects_what_readers_reject(self, change: dict) -> None:
        manifest = json.loads((HERE / "examples/rust.json").read_text()) | change

        assert errors_of(manifest) != []


class TestRustWriter:
    def test_output_matches_the_example(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "persons_migrations").mkdir()
            (base / "behavioral_cohorts_migrations").mkdir()
            for name in ["20251113000001_b.sql", "20250923000001_a.sql", "20250923000001_a.down.sql"]:
                (base / "persons_migrations" / name).touch()
            (base / "behavioral_cohorts_migrations" / "20250113000001_c.sql").touch()

            manifest = run_rust_writer("persons behavioral-cohorts", base, base / "out.json")

            assert manifest == json.loads((HERE / "examples/rust.json").read_text())

    def test_output_for_the_real_migrations_matches_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = run_rust_writer(
                "persons behavioral-cohorts cyclotron-node flags-read-store", REPO_ROOT / "rust", Path(tmp) / "out.json"
            )

        assert errors_of(manifest) == []
        assert manifest["digest"] == digest_of(manifest["requirements"])
