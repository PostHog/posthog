from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from click.testing import CliRunner
from hogli_commands.quarantine import core
from hogli_commands.quarantine.cli import quarantine
from hogli_commands.quarantine.pytest_support import apply_quarantine_markers

TODAY = date(2026, 6, 10)


def make_entry(**overrides: Any) -> core.Entry:
    defaults: dict[str, Any] = {
        "id": "posthog/api/test/test_foo.py::TestFoo::test_bar",
        "added": TODAY,
        "expires": TODAY + timedelta(days=14),
        "reason": "flaky",
        "owner": "@team-devex",
    }
    return core.Entry(**{**defaults, **overrides})


def write_file(path: Path, entries: list[dict[str, Any]], version: int = 1) -> Path:
    path.write_text(json.dumps({"version": version, "entries": entries}, indent=4) + "\n")
    return path


def raw_entry(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id": "posthog/api/test/test_foo.py::TestFoo::test_bar",
        "runner": "pytest",
        "reason": "flaky",
        "owner": "@team-devex",
        "added": core.today_utc().isoformat(),
        "expires": (core.today_utc() + timedelta(days=14)).isoformat(),
        "mode": "run",
    }
    return {**defaults, **overrides}


@pytest.mark.parametrize(
    "selector, test_id, expected",
    [
        # exact nodeid
        ("posthog/api/test/test_foo.py::TestFoo::test_bar", "posthog/api/test/test_foo.py::TestFoo::test_bar", True),
        # function selector covers parameterized variants
        (
            "posthog/api/test/test_foo.py::TestFoo::test_bar",
            "posthog/api/test/test_foo.py::TestFoo::test_bar[a-1]",
            True,
        ),
        # class prefix
        ("posthog/api/test/test_foo.py::TestFoo", "posthog/api/test/test_foo.py::TestFoo::test_other", True),
        # file prefix
        ("posthog/api/test/test_foo.py", "posthog/api/test/test_foo.py::TestBar::test_x", True),
        # directory prefix, with and without trailing slash
        ("posthog/api/test", "posthog/api/test/test_foo.py::TestFoo::test_bar", True),
        ("posthog/api/test/", "posthog/api/test/test_foo.py::TestFoo::test_bar", True),
        # partial names never match
        ("posthog/api/test", "posthog/api/test_organization.py::test_x", False),
        (
            "posthog/api/test/test_foo.py::TestFoo::test_bar",
            "posthog/api/test/test_foo.py::TestFoo::test_barbell",
            False,
        ),
        # product selector translates dashes to the underscored directory
        ("product:batch-exports", "products/batch_exports/backend/tests/test_runs.py::test_x", True),
        ("product:batch-exports", "products/batch_exports_v2/backend/tests/test_runs.py::test_x", False),
        ("product:batch-exports", "posthog/api/test/test_foo.py::test_x", False),
        # unrelated paths
        ("posthog/api/test/test_foo.py", "posthog/api/test/test_food.py::test_x", False),
    ],
)
def test_selector_matches(selector: str, test_id: str, expected: bool) -> None:
    assert core.selector_matches(selector, test_id) is expected


@pytest.mark.parametrize(
    "expires_offset_days, expected_active",
    [(-1, False), (0, True), (1, True)],
)
def test_expiry_boundary(expires_offset_days: int, expected_active: bool) -> None:
    entry = make_entry(expires=TODAY + timedelta(days=expires_offset_days))
    assert core.is_active(entry, TODAY) is expected_active


def test_active_entries_filters_runner_and_expiry() -> None:
    entries = [
        make_entry(id="a"),
        make_entry(id="b", expires=TODAY - timedelta(days=1)),
        make_entry(id="c", runner="jest"),
        make_entry(id="d", runner="some-future-runner"),
    ]
    assert [e.id for e in core.active_entries(entries, "pytest", TODAY)] == ["a"]


def test_load_missing_file_is_empty_and_clean(tmp_path: Path) -> None:
    result = core.load(tmp_path / "nope.json")
    assert result.entries == []
    assert result.errors == []


@pytest.mark.parametrize(
    "text, error_fragment",
    [
        ("not json{", "invalid JSON"),
        ("[]", "top level"),
        ('{"version": 2, "entries": []}', "unsupported version"),
        ('{"version": 1, "entries": {}}', "must be a list"),
    ],
)
def test_parse_malformed_file_reports_error_without_entries(text: str, error_fragment: str) -> None:
    result = core.parse(text)
    assert result.entries == []
    assert any(error_fragment in e for e in result.errors)


@pytest.mark.parametrize(
    "broken",
    [
        {"id": "", "added": "2026-06-10", "expires": "2026-06-20"},
        {"id": "x", "added": "not-a-date", "expires": "2026-06-20"},
        {"id": "x", "added": "2026-06-10", "expires": "2026-06-20", "mode": "pause"},
        {"id": "x", "added": "2026-06-10", "expires": "2026-06-20", "reason": 42},
        "not-an-object",
    ],
)
def test_parse_skips_broken_entry_but_keeps_good_ones(broken: Any) -> None:
    good = {"id": "posthog/a.py", "added": "2026-06-10", "expires": "2026-06-20"}
    result = core.parse(json.dumps({"version": 1, "entries": [broken, good]}))
    assert [e.id for e in result.entries] == ["posthog/a.py"]
    assert len(result.errors) == 1


def test_parse_warns_on_unknown_field_and_preserves_it_on_render() -> None:
    entry = {"id": "posthog/a.py", "added": "2026-06-10", "expires": "2026-06-20", "future_field": "x"}
    result = core.parse(json.dumps({"version": 1, "entries": [entry], "future_top_level": True}))
    assert result.errors == []
    assert any("future_field" in w for w in result.warnings)
    rendered = json.loads(core.render(result.entries, result.extras))
    assert rendered["future_top_level"] is True
    assert rendered["entries"][0]["future_field"] == "x"


def test_render_is_sorted_indented_and_newline_terminated() -> None:
    text = core.render([make_entry(id="z/b.py"), make_entry(id="a/a.py")])
    assert text.endswith("}\n")
    assert '    "version": 1' in text
    ids = [e["id"] for e in json.loads(text)["entries"]]
    assert ids == sorted(ids)


# ---------- pytest adapter ----------


class FakeItem:
    def __init__(self, nodeid: str) -> None:
        self.nodeid = nodeid
        self.markers: list[Any] = []

    def add_marker(self, marker: Any) -> None:
        self.markers.append(marker)

    def get_closest_marker(self, name: str) -> Any:
        return next((m for m in self.markers if m.name == name), None)

    def marker_names(self) -> list[str]:
        return [m.name for m in self.markers]


def test_adapter_marks_matching_item_xfail(tmp_path: Path) -> None:
    path = write_file(tmp_path / "q.json", [raw_entry()])
    item = FakeItem("posthog/api/test/test_foo.py::TestFoo::test_bar")
    other = FakeItem("posthog/api/test/test_other.py::test_x")
    apply_quarantine_markers([item, other], path=path)  # type: ignore[arg-type]
    assert item.marker_names() == ["quarantine", "xfail"]
    assert "quarantined until" in item.markers[1].kwargs["reason"]
    assert other.markers == []


def test_adapter_skip_mode_applies_skip_marker(tmp_path: Path) -> None:
    path = write_file(tmp_path / "q.json", [raw_entry(mode="skip")])
    item = FakeItem("posthog/api/test/test_foo.py::TestFoo::test_bar")
    apply_quarantine_markers([item], path=path)  # type: ignore[arg-type]
    assert item.marker_names() == ["quarantine", "skip"]


def test_adapter_most_specific_selector_wins(tmp_path: Path) -> None:
    entries = [
        raw_entry(id="posthog/api/test/test_foo.py", mode="run"),
        raw_entry(id="posthog/api/test/test_foo.py::TestFoo::test_bar", mode="skip"),
    ]
    path = write_file(tmp_path / "q.json", entries)
    narrow = FakeItem("posthog/api/test/test_foo.py::TestFoo::test_bar")
    broad = FakeItem("posthog/api/test/test_foo.py::TestFoo::test_other")
    apply_quarantine_markers([narrow, broad], path=path)  # type: ignore[arg-type]
    assert narrow.marker_names() == ["quarantine", "skip"]
    assert broad.marker_names() == ["quarantine", "xfail"]


def test_adapter_is_idempotent_across_double_registration(tmp_path: Path) -> None:
    path = write_file(tmp_path / "q.json", [raw_entry()])
    item = FakeItem("posthog/api/test/test_foo.py::TestFoo::test_bar")
    apply_quarantine_markers([item], path=path)  # type: ignore[arg-type]
    apply_quarantine_markers([item], path=path)  # type: ignore[arg-type]
    assert item.marker_names() == ["quarantine", "xfail"]


@pytest.mark.parametrize(
    "entry",
    [
        raw_entry(expires="2020-01-01"),  # expired → inert
        raw_entry(runner="jest"),  # other runner → not pytest's business
        raw_entry(runner="never-heard-of-it"),  # unknown runner → ignored, not an error
    ],
)
def test_adapter_leaves_item_unmarked(tmp_path: Path, entry: dict[str, Any]) -> None:
    path = write_file(tmp_path / "q.json", [entry])
    item = FakeItem("posthog/api/test/test_foo.py::TestFoo::test_bar")
    apply_quarantine_markers([item], path=path)  # type: ignore[arg-type]
    assert item.markers == []


def test_adapter_fails_open_on_malformed_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "q.json"
    path.write_text("not json{")
    item = FakeItem("posthog/api/test/test_foo.py::TestFoo::test_bar")
    apply_quarantine_markers([item], path=path)  # type: ignore[arg-type]
    assert item.markers == []
    assert "[quarantine]" in capsys.readouterr().err


# ---------- CLI ----------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def cli(runner: CliRunner, path: Path, *args: str) -> Any:
    return runner.invoke(quarantine, ["--file", str(path), *args])


def test_add_creates_canonical_file(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    result = cli(runner, path, "add", "posthog/api/test/test_foo.py", "--reason", "flaky", "--owner", "@team-devex")
    assert result.exit_code == 0, result.output
    text = path.read_text()
    assert text.endswith("\n")
    data = json.loads(text)
    entry = data["entries"][0]
    assert entry["id"] == "posthog/api/test/test_foo.py"
    assert entry["mode"] == "run"
    assert date.fromisoformat(entry["expires"]) - date.fromisoformat(entry["added"]) == timedelta(days=14)


def test_add_replaces_existing_entry_with_same_id(runner: CliRunner, tmp_path: Path) -> None:
    path = write_file(tmp_path / "q.json", [raw_entry(reason="old")])
    result = cli(runner, path, "add", raw_entry()["id"], "--reason", "new", "--owner", "@x", "--mode", "skip")
    assert result.exit_code == 0, result.output
    entries = json.loads(path.read_text())["entries"]
    assert len(entries) == 1
    assert entries[0]["reason"] == "new"
    assert entries[0]["mode"] == "skip"


@pytest.mark.parametrize(
    "argv",
    [
        ("add", "x.py", "--reason", "r", "--owner", "@o", "--days", "31"),  # over the cap
        ("add", "x.py", "--reason", "r", "--owner", "@o", "--days", "0"),
        ("add", "/abs/path.py", "--reason", "r", "--owner", "@o"),  # absolute selector
        ("add", "product:no_such_product", "--reason", "r", "--owner", "@o"),  # underscored / unknown product
        ("add", "x.py", "--owner", "@o"),  # missing --reason
    ],
)
def test_add_rejects_invalid_input(runner: CliRunner, tmp_path: Path, argv: tuple[str, ...]) -> None:
    path = tmp_path / "q.json"
    result = cli(runner, path, *argv)
    assert result.exit_code != 0
    assert not path.exists()


def test_add_refuses_to_rewrite_malformed_file(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text("not json{")
    result = cli(runner, path, "add", "x.py", "--reason", "r", "--owner", "@o")
    assert result.exit_code != 0
    assert path.read_text() == "not json{"


def test_remove_absent_id_succeeds(runner: CliRunner, tmp_path: Path) -> None:
    path = write_file(tmp_path / "q.json", [raw_entry()])
    result = cli(runner, path, "remove", "posthog/never/was/quarantined.py")
    assert result.exit_code == 0
    assert "nothing to do" in result.output
    assert len(json.loads(path.read_text())["entries"]) == 1


def test_remove_deletes_entry(runner: CliRunner, tmp_path: Path) -> None:
    path = write_file(tmp_path / "q.json", [raw_entry()])
    result = cli(runner, path, "remove", raw_entry()["id"])
    assert result.exit_code == 0
    assert json.loads(path.read_text())["entries"] == []


def test_list_json_emits_canonical_document(runner: CliRunner, tmp_path: Path) -> None:
    path = write_file(tmp_path / "q.json", [raw_entry()])
    result = cli(runner, path, "list", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output)["version"] == 1


def test_list_shows_status(runner: CliRunner, tmp_path: Path) -> None:
    path = write_file(tmp_path / "q.json", [raw_entry()])
    result = cli(runner, path, "list")
    assert result.exit_code == 0
    assert "expires in" in result.output
    assert "@team-devex" in result.output


@pytest.mark.parametrize(
    "entries, expected_exit, expected_fragment",
    [
        # healthy file
        ([raw_entry()], 0, "OK"),
        # duplicate ids
        ([raw_entry(), raw_entry(reason="again")], 1, "duplicate id"),
        # cap exceeded
        ([raw_entry(expires=(core.today_utc() + timedelta(days=40)).isoformat())], 1, "exceeds 30 days"),
        # expires before added
        ([raw_entry(expires=(core.today_utc() - timedelta(days=1)).isoformat())], 1, "before added"),
        # expired beyond the grace period
        (
            [
                raw_entry(
                    added=(core.today_utc() - timedelta(days=30)).isoformat(),
                    expires=(core.today_utc() - timedelta(days=10)).isoformat(),
                )
            ],
            1,
            "remove or re-triage",
        ),
        # expired but within grace → warn, pass
        (
            [
                raw_entry(
                    added=(core.today_utc() - timedelta(days=20)).isoformat(),
                    expires=(core.today_utc() - timedelta(days=3)).isoformat(),
                )
            ],
            0,
            "remove within",
        ),
        # expired exactly grace days ago → last day of grace, warn without "within 0 days"
        (
            [
                raw_entry(
                    added=(core.today_utc() - timedelta(days=27)).isoformat(),
                    expires=(core.today_utc() - timedelta(days=7)).isoformat(),
                )
            ],
            0,
            "remove today — grace period ends",
        ),
        # forward compat: unknown runner and unknown field warn but pass
        ([raw_entry(runner="jest", future_field="x")], 0, "no enforcement adapter"),
        # known-product selector passes; unknown product fails
        ([raw_entry(id="product:batch-exports")], 0, "OK"),
        ([raw_entry(id="product:batch_exports")], 1, "dashed product name"),
    ],
)
def test_check(
    runner: CliRunner, tmp_path: Path, entries: list[dict[str, Any]], expected_exit: int, expected_fragment: str
) -> None:
    path = write_file(tmp_path / "q.json", entries)
    result = cli(runner, path, "check")
    assert result.exit_code == expected_exit, result.output
    assert expected_fragment in result.output


def test_check_fails_on_malformed_file(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    path.write_text('{"version": 99}')
    result = cli(runner, path, "check")
    assert result.exit_code == 1
    assert "unsupported version" in result.output


def test_check_passes_on_missing_file(runner: CliRunner, tmp_path: Path) -> None:
    result = cli(runner, tmp_path / "missing.json", "check")
    assert result.exit_code == 0


def test_repo_quarantine_file_is_valid(runner: CliRunner) -> None:
    assert core.QUARANTINE_PATH.name == ".test_quarantine.json"
    result = runner.invoke(quarantine, ["check"])
    assert result.exit_code == 0, result.output
