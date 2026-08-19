from __future__ import annotations

import ast
from pathlib import Path

import pytest
from unittest.mock import patch

from hogli_commands import test_audit


def _hash(source: str) -> tuple[str, int]:
    func = ast.parse(source).body[0]
    assert isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    return test_audit._body_hash(func)


@pytest.mark.parametrize(
    "a, b, same",
    [
        (
            "def test_a():\n    x = call(1, 'one')\n    y = call(2, 'two')\n    z = call(3, 'three')\n    assert x == y == z",
            "def test_b():\n    x = call(4, 'four')\n    y = call(5, 'five')\n    z = call(6, 'six')\n    assert x == y == z",
            True,
        ),
        (
            "def test_a():\n    result = fn(alpha=1)\n    assert result\n    assert result.ok\n    assert result.done",
            "def test_b():\n    result = fn(alpha=1)\n    assert not result\n    assert result.ok\n    assert result.done",
            False,
        ),
    ],
)
def test_body_hash_matches_copy_paste_but_not_real_differences(a: str, b: str, same: bool) -> None:
    assert (_hash(a)[0] == _hash(b)[0]) is same


def test_body_hash_size_counts_nested_def_bodies() -> None:
    _, size = _hash(
        "def test_a():\n    def helper():\n        return 1\n    x = helper()\n    assert x\n    assert True"
    )
    assert size == 5


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_dupes_clusters_across_files_and_skips_tiny_bodies(tmp_path: Path) -> None:
    big = "    x = call({n})\n    y = call({n})\n    z = call({n})\n    assert x == y == z\n"
    for i in range(3):
        _write(tmp_path / f"pkg/test_copy_{i}.py", f"def test_thing_{i}():\n" + big.format(n=i))
    _write(tmp_path / "pkg/test_tiny.py", "def test_small():\n    assert True\n")

    with patch.object(
        test_audit, "_test_files", return_value=[str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*.py")]
    ):
        clusters = test_audit._dupes(tmp_path, {})

    assert len(clusters) == 1
    assert len(clusters[0].members) == 3
    assert all("test_tiny.py" not in nodeid for nodeid in clusters[0].members)


def test_dupes_estimates_seconds_from_durations(tmp_path: Path) -> None:
    body = "        x = call({n})\n        y = call({n})\n        z = call({n})\n        assert x == y == z\n"
    for i in range(3):
        _write(
            tmp_path / f"pkg/test_copy_{i}.py",
            f"class TestGroup:\n    def test_thing_{i}(self):\n" + body.format(n=i),
        )

    durations = {f"pkg/test_copy_{i}.py::TestGroup::test_thing_{i}": 2.0 * (i + 1) for i in range(3)}
    with patch.object(test_audit, "_test_files", return_value=[f"pkg/test_copy_{i}.py" for i in range(3)]):
        clusters = test_audit._dupes(tmp_path, durations)

    assert clusters[0].seconds == 12.0
