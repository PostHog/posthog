from __future__ import annotations

import sys
import json
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _span(span_id: str, parent_span_id: str = "0000000000000000") -> dict:
    return {
        "trace_id": "0123456789abcdef0123456789abcdef",
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "is_root_span": parent_span_id == "0000000000000000",
        "name": f"span {span_id}",
        "service_name": "api",
        "kind": 2,
        "status_code": 1,
        "duration_nano": 1_000_000,
    }


def _write_persisted_page(path: Path, spans: list[dict], has_more: bool, next_offset: int | None) -> Path:
    payload = json.dumps({"results": spans, "hasMore": has_more, "nextOffset": next_offset})
    text = f'Trace data below.\n<trace-data informational="true">\n{payload}\n</trace-data>'
    path.write_text(json.dumps([{"type": "text", "text": text}]))
    return path


def _run(script: str, *args: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_merges_every_page_into_one_trace_the_other_scripts_read(tmp_path: Path) -> None:
    first = _write_persisted_page(tmp_path / "page-0.json", [_span("a"), _span("b", "a")], True, 2)
    # A span ingested between calls shifts the start-time ordering, so the next page can repeat "b".
    second = _write_persisted_page(tmp_path / "page-2.json", [_span("b", "a"), _span("c", "b")], False, None)

    merged = _run("merge_pages.py", first, second)

    assert merged.returncode == 0, merged.stderr
    assert [span["span_id"] for span in json.loads(merged.stdout)["results"]] == ["a", "b", "c"]
    assert "Incomplete" not in merged.stderr

    merged_file = tmp_path / "trace.json"
    merged_file.write_text(merged.stdout)
    summary = _run("print_summary.py", merged_file)

    assert summary.returncode == 0, summary.stderr
    assert "Span count:  3" in summary.stdout


def test_warns_when_the_last_page_was_not_fetched(tmp_path: Path) -> None:
    first = _write_persisted_page(tmp_path / "page-0.json", [_span("a")], True, 2000)

    merged = _run("merge_pages.py", first)

    assert merged.returncode == 0, merged.stderr
    assert "offset: 2000" in merged.stderr
