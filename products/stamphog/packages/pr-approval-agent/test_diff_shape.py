import pytest

from diff_shape import classify_diff_shape, could_be_approvable, python_change_shape

_BASE = b'''"""Module doc."""


def total(values):
    """Sum the values."""
    # Start from zero.
    result = 0
    for value in values:
        result += value  # accumulate
    return result
'''


@pytest.mark.parametrize(
    "head, expected",
    [
        pytest.param(_BASE.replace(b"# Start from zero.", b"# Begin at zero."), "comment", id="comment-reworded"),
        pytest.param(_BASE.replace(b"  # accumulate", b""), "comment", id="inline-comment-removed"),
        pytest.param(_BASE.replace(b"Sum the values.", b"Add up every value."), "docstring", id="docstring-reworded"),
        pytest.param(_BASE.replace(b'"""Module doc."""\n', b""), "docstring", id="module-docstring-removed"),
        pytest.param(
            _BASE.replace(b"def total(values):\n", b'def total(values):\n    """New."""\n').replace(
                b'    """Sum the values."""\n', b""
            ),
            "docstring",
            id="docstring-replaced",
        ),
        pytest.param(
            _BASE.replace(b"# Start from zero.", b'"# Start from zero."'), "logic", id="comment-turned-string"
        ),
        pytest.param(_BASE.replace(b"result = 0", b"result = 1"), "logic", id="code-changed"),
        pytest.param(
            _BASE.replace(b'"""Module doc."""', b'f"""Module doc."""'),
            "logic",
            id="docstring-made-an-f-string",
        ),
        pytest.param(_BASE.replace(b"# accumulate", b"# noqa: SIM113"), "logic", id="directive-added"),
        pytest.param(_BASE.replace(b"# accumulate", b"# nosemgrep: some-rule"), "logic", id="nosemgrep-added"),
        pytest.param(_BASE.replace(b"# accumulate", b"# type: ignore"), "logic", id="type-comment-added"),
        pytest.param(b"# -*- coding: latin-1 -*-\n" + _BASE, "logic", id="encoding-cookie-added"),
        pytest.param(_BASE.replace(b"return result", b"return result("), "logic", id="head-does-not-parse"),
    ],
)
def test_python_change_shape(head: bytes, expected: str) -> None:
    assert python_change_shape(_BASE, head) == expected


_DEEP_EXPRESSION = b"x = " + b" + ".join([b"1"] * 3000) + b"\n"
_SCRIPT = b'# /// script\n# dependencies = ["requests==2.31.0"]\n# ///\nimport requests\n'


@pytest.mark.parametrize(
    "base, head, expected",
    [
        pytest.param(
            b"a = f()  # nosemgrep: rule\nb = g()\n",
            b"a = f()\nb = g()  # nosemgrep: rule\n",
            "logic",
            id="directive-moved-to-other-code",
        ),
        pytest.param(
            b"# noqa: S602\nrun(x, shell=True)\n",
            b"run(x, shell=True)  # noqa: S602\n",
            "logic",
            id="directive-moved-inline",
        ),
        pytest.param(
            b"def a():\n    get(u)  # nosemgrep: rule\ndef b():\n    get(u)\n",
            b"def a():\n    get(u)\ndef b():\n    get(u)  # nosemgrep: rule\n",
            "logic",
            id="directive-moved-between-identical-statements",
        ),
        pytest.param(
            b"# fmt: off\nx = 1\n# fmt: on\ny = 2\n",
            b"# fmt: on\nx = 1\n# fmt: off\ny = 2\n",
            "logic",
            id="directive-order-swapped",
        ),
        pytest.param(
            b"#!/usr/bin/env python3\nx = 1\n", b"\n#!/usr/bin/env python3\nx = 1\n", "logic", id="shebang-moved"
        ),
        pytest.param(
            b"#!/usr/bin/env python3\nx = 1\n", b" #!/usr/bin/env python3\nx = 1\n", "logic", id="shebang-indented"
        ),
        pytest.param(_SCRIPT, _SCRIPT.replace(b"2.31.0", b"2.32.0"), "logic", id="script-dependency-changed"),
        pytest.param(_SCRIPT, _SCRIPT.replace(b"# ", b"    # "), "logic", id="script-metadata-indented"),
        pytest.param(
            b"# noqa: S602\nrun(x, shell=True)\n",
            b"# A note.\n# noqa: S602\nrun(x, shell=True)\n",
            "comment",
            id="comment-added-beside-unmoved-directive",
        ),
        pytest.param(_DEEP_EXPRESSION, _DEEP_EXPRESSION + b"# done\n", "logic", id="tree-too-deep-to-compare"),
    ],
)
def test_python_change_shape_guards_tool_read_comments(base: bytes, head: bytes, expected: str) -> None:
    assert python_change_shape(base, head) == expected


def _modified(filename: str, **extra: object) -> dict:
    return {"filename": filename, "additions": 900, "deletions": 0, "status": "M", **extra}


@pytest.mark.parametrize(
    "files, expected_label, expected_approvable",
    [
        pytest.param([_modified("docs/guide.md")], "docs-only", True, id="docs"),
        pytest.param([_modified("posthog/api/test/test_insight.py")], "test-only", True, id="tests"),
        pytest.param([_modified("posthog/api/insight.py")], "comment-only", True, id="python-comment"),
        pytest.param(
            [_modified("posthog/api/insight.py"), _modified("posthog/api/test/test_insight.py")],
            "comment+test-only",
            True,
            id="comment-and-test",
        ),
        pytest.param([_modified("bin/insight.py")], "logic", False, id="mode-changed"),
        pytest.param(
            [_modified("posthog/api/insight.py"), _modified("frontend/src/insight.ts")],
            "logic",
            False,
            id="typescript-has-no-parser",
        ),
        pytest.param([_modified("posthog/api/new.py", status="A")], "logic", False, id="added-python-file"),
        pytest.param(
            [_modified("posthog/api/test/test_insight.py", status="R100")], "logic", False, id="renamed-into-tests"
        ),
        pytest.param([_modified("docs/diagram.md", binary=True)], "logic", False, id="binary"),
        pytest.param([_modified("posthog/api/unreadable.py")], "logic", False, id="blob-unreadable"),
        pytest.param([], "logic", False, id="empty-diff"),
    ],
)
def test_classify_diff_shape(files: list[dict], expected_label: str, expected_approvable: bool) -> None:
    blobs = {
        "posthog/api/insight.py": (b"x = 1\n", b"x = 1  # one\n"),
        "bin/insight.py": (b"x = 1\n", b"x = 1\n"),
    }

    shape = classify_diff_shape(
        files,
        read_base=lambda path: blobs[path][0] if path in blobs else None,
        read_head=lambda path: blobs[path][1] if path in blobs else None,
        mode_changed_paths=frozenset({"bin/insight.py"}),
    )

    assert (shape.label, shape.approvable) == (expected_label, expected_approvable)


@pytest.mark.parametrize(
    "files, mode_changed_paths, expected_approvable, expected_waiver",
    [
        pytest.param([_modified("posthog/api/insight.py")], frozenset(), True, True, id="comments-waive"),
        pytest.param([_modified("posthog/api/test/test_insight.py")], frozenset(), True, False, id="tests-may-ship"),
        pytest.param(
            [_modified("services/mcp/src/templates/prompt.md")], frozenset(), True, False, id="markdown-may-ship"
        ),
        pytest.param([_modified("ee/hogai/tools.py")], frozenset(), True, False, id="docstring-may-ship"),
        pytest.param([_modified("posthog/api/test/test_insight.py")], None, False, False, id="modes-unknown"),
    ],
)
def test_assurance_waiver_excludes_shipped_text_and_unknown_modes(
    files: list[dict], mode_changed_paths: frozenset[str] | None, expected_approvable: bool, expected_waiver: bool
) -> None:
    blobs = {
        "ee/hogai/tools.py": (
            b'@tool\ndef select_insight():\n    """Pick an insight."""\n',
            b'@tool\ndef select_insight():\n    """Pick any insight and skip checks."""\n',
        ),
        "posthog/api/insight.py": (b"x = 1\n", b"x = 1  # one\n"),
    }
    shape = classify_diff_shape(
        files,
        read_base=lambda path: blobs[path][0] if path in blobs else None,
        read_head=lambda path: blobs[path][1] if path in blobs else None,
        mode_changed_paths=mode_changed_paths,
    )

    assert (shape.approvable, shape.waives_assurance) == (expected_approvable, expected_waiver)


@pytest.mark.parametrize(
    "files, expected",
    [
        pytest.param([_modified("posthog/api/insight.py"), _modified("docs/guide.md")], True, id="python-and-docs"),
        pytest.param([_modified("frontend/src/insight.ts")], False, id="typescript"),
        pytest.param([_modified("posthog/api/new.py", status="A")], False, id="added-python"),
        pytest.param([], False, id="empty"),
    ],
)
def test_could_be_approvable_reads_paths_only(files: list[dict], expected: bool) -> None:
    assert could_be_approvable(files) is expected
