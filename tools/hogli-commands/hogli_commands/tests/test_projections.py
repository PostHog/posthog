from __future__ import annotations

import sys
import importlib.metadata
from pathlib import Path

import pytest

import click
from hogli_commands.projections import (
    BIOME,
    OXFMT,
    RUFF,
    Formatter,
    OutputFormatter,
    Projection,
    ProjectionRunner,
    Tier,
    _select,
    formatter_for,
)

RENDERER = """
def render():
    return {"out/first.generated.ts": "first\\n", "out/second.json": "{}"}
"""

PROJECTION = Projection(
    name="fake",
    renderer="fake_projection.py",
    inputs=("fake/*",),
    outputs=("out/first.generated.ts", "out/second.json"),
)


class UnchangedFormatter(OutputFormatter):
    def format(self, path: str, text: str) -> str:
        return text


class MarkingFormatter(OutputFormatter):
    def format(self, path: str, text: str) -> str:
        return f"// formatted\n{text}"


def _runner(
    tmp_path: Path,
    renderer: str = RENDERER,
    projection: Projection = PROJECTION,
    formatter: type[OutputFormatter] = UnchangedFormatter,
) -> ProjectionRunner:
    (tmp_path / projection.renderer).write_text(renderer)
    return ProjectionRunner(tmp_path, [projection], formatter(tmp_path))


class TestProjectionRunner:
    @pytest.mark.parametrize(
        "on_disk,expected_stale",
        [
            ({}, ["out/first.generated.ts", "out/second.json"]),
            ({"out/first.generated.ts": "first\n", "out/second.json": "{ }"}, ["out/second.json"]),
            ({"out/first.generated.ts": "first\r\n", "out/second.json": "{}"}, ["out/first.generated.ts"]),
            ({"out/first.generated.ts": "first\n", "out/second.json": "{}"}, []),
        ],
        ids=["missing", "one-output-drifted", "newline-translated", "in-sync"],
    )
    def test_stale_compares_every_output_byte_for_byte(
        self, tmp_path: Path, on_disk: dict[str, str], expected_stale: list[str]
    ) -> None:
        runner = _runner(tmp_path)
        for path, contents in on_disk.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_bytes(contents.encode())

        assert runner.stale(PROJECTION) == expected_stale

    def test_stale_writes_nothing_and_write_clears_it(self, tmp_path: Path) -> None:
        runner = _runner(tmp_path)

        assert runner.stale(PROJECTION) != []
        assert not (tmp_path / "out").exists()

        assert runner.write(PROJECTION) == ["out/first.generated.ts", "out/second.json"]
        assert runner.stale(PROJECTION) == []
        assert runner.write(PROJECTION) == []

    def test_formatted_output_is_what_gets_compared_and_written(self, tmp_path: Path) -> None:
        runner = _runner(tmp_path, formatter=MarkingFormatter)
        (tmp_path / "out").mkdir()
        (tmp_path / "out/first.generated.ts").write_text("first\n")
        (tmp_path / "out/second.json").write_text("// formatted\n{}")

        assert runner.stale(PROJECTION) == ["out/first.generated.ts"]

        runner.write(PROJECTION)
        assert (tmp_path / "out/first.generated.ts").read_text() == "// formatted\nfirst\n"

    def test_a_renderer_that_refuses_reports_its_reason_without_writing(self, tmp_path: Path) -> None:
        refusing = 'def render():\n    raise ValueError("Stripe: stripe -> stripe-test")\n'
        runner = _runner(tmp_path, renderer=refusing)

        with pytest.raises(click.ClickException, match="fake: Stripe: stripe -> stripe-test"):
            runner.write(PROJECTION)
        assert not (tmp_path / "out").exists()

    def test_renderer_outputs_must_match_the_registry(self, tmp_path: Path) -> None:
        undeclared = RENDERER.replace('"out/second.json": "{}"', '"out/other.json": "{}"')
        runner = _runner(tmp_path, renderer=undeclared)

        with pytest.raises(click.ClickException, match="Keep the two in step"):
            runner.stale(PROJECTION)


def _uv_lock(tmp_path: Path, version: str) -> None:
    (tmp_path / "uv.lock").write_text(f'version = 1\n\n[[package]]\nname = "ruff"\nversion = "{version}"\n')


class TestRuffFormatter:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("posthog/integrations/kinds_generated.py", RUFF),
            ("products/desktop/scripts/tool.py", RUFF),
            ("frontend/src/lib/oauthScopes.generated.ts", OXFMT),
            ("products/desktop/packages/core/src/a.generated.ts", BIOME),
            ("products/warehouse_sources/backend/field_classification.csv", None),
        ],
    )
    def test_formatter_for_picks_ruff_for_python(self, path: str, expected: Formatter | None) -> None:
        assert formatter_for(path) == expected

    @pytest.mark.parametrize(
        "locked_matches,expected_prefix",
        [(True, [sys.executable, "-m", "ruff"]), (False, ["uvx", "ruff==0.0.1"])],
        ids=["installed-version-matches-the-lock", "falls-back-to-the-locked-version"],
    )
    def test_ruff_runs_from_the_environment_only_at_the_locked_version(
        self, tmp_path: Path, locked_matches: bool, expected_prefix: list[str]
    ) -> None:
        _uv_lock(tmp_path, importlib.metadata.version("ruff") if locked_matches else "0.0.1")

        assert OutputFormatter(tmp_path)._command(RUFF) == expected_prefix

    def test_formats_python_output(self, tmp_path: Path) -> None:
        _uv_lock(tmp_path, importlib.metadata.version("ruff"))

        assert OutputFormatter(tmp_path).format("out/kinds.py", "x={ 'a':1 }") == 'x = {"a": 1}\n'

    def test_output_without_a_formatter_is_written_as_rendered(self, tmp_path: Path) -> None:
        assert OutputFormatter(tmp_path).format("out/table.csv", "a,b\n1,2\n") == "a,b\n1,2\n"


class TestTiers:
    def test_a_projection_that_sets_django_up_cannot_join_the_preflight_tier(self) -> None:
        with pytest.raises(ValueError, match="must use Tier.CI"):
            Projection(name="heavy", renderer="heavy.py", inputs=(), outputs=("out/heavy.json",), django=True)

    def test_the_preflight_tier_leaves_out_the_django_projections(self) -> None:
        preflight = {projection.name for projection in _select((), Tier.PREFLIGHT)}
        everything = {projection.name for projection in _select(())}

        assert "warehouse-source-fields" in everything
        assert "warehouse-source-fields" not in preflight
        assert "taxonomy" in preflight
