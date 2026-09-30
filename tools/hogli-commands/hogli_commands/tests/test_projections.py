from __future__ import annotations

from pathlib import Path

import pytest

import click
from hogli_commands.projections import Projection, ProjectionRunner

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


def _runner(tmp_path: Path, renderer: str = RENDERER, projection: Projection = PROJECTION) -> ProjectionRunner:
    (tmp_path / projection.renderer).write_text(renderer)
    return ProjectionRunner(tmp_path, [projection])


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

    def test_renderer_outputs_must_match_the_registry(self, tmp_path: Path) -> None:
        undeclared = RENDERER.replace('"out/second.json": "{}"', '"out/other.json": "{}"')
        runner = _runner(tmp_path, renderer=undeclared)

        with pytest.raises(click.ClickException, match="Keep the two in step"):
            runner.stale(PROJECTION)
