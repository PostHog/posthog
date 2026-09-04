from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest

from click.testing import CliRunner
from hogli_commands.quarantine import core, report
from hogli_commands.quarantine.cli import quarantine
from hogli_commands.quarantine.pytest_support import apply_quarantine_markers

TODAY = date(2026, 6, 10)
WALL_CLOCK_TODAY_UTC = core.today_utc


@pytest.fixture(autouse=True)
def pin_today_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "today_utc", lambda: TODAY)


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
        "added": TODAY.isoformat(),
        "expires": (TODAY + timedelta(days=14)).isoformat(),
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
        # jest ids: file::<space-joined test name>; a file selector covers every test in it
        ("frontend/src/x.test.ts", "frontend/src/x.test.ts::MyLogic loads data", True),
        # describe-block prefix matches via the space boundary
        ("frontend/src/x.test.ts::MyLogic", "frontend/src/x.test.ts::MyLogic loads data", True),
        # exact full test name
        ("frontend/src/x.test.ts::MyLogic loads data", "frontend/src/x.test.ts::MyLogic loads data", True),
        # a partial describe word never matches (space, not substring)
        ("frontend/src/x.test.ts::MyLog", "frontend/src/x.test.ts::MyLogic loads data", False),
    ],
)
def test_selector_matches(selector: str, test_id: str, expected: bool) -> None:
    assert core.selector_matches(selector, test_id) is expected


@pytest.mark.parametrize(
    "selector, runner, valid",
    [
        ("frontend/src/x.test.ts", "jest", True),
        ("frontend/src/x.test.ts::MyLogic loads data", "jest", True),  # spaces allowed after ::
        ("frontend/src", "jest", True),
        ("product:batch-exports", "jest", True),  # product rule shared with pytest
        ("/abs/x.test.ts", "jest", False),  # absolute path
        ("frontend/src/x test.ts::name", "jest", False),  # whitespace in the path part
        ("::name-only", "jest", False),  # missing file path before ::
        ("product:batch_exports", "jest", False),  # underscored product form
        ("playwright/e2e/login.spec.ts::Login redirects home", "playwright", True),  # spaces allowed after ::
        ("playwright/e2e/login file.spec.ts::Login", "playwright", False),  # whitespace in the path part
        ("anything at all", "some-future-runner", True),  # unadapted runner: not validated
    ],
)
def test_validate_selector_by_runner(selector: str, runner: str, valid: bool) -> None:
    assert (core.validate_selector(selector, runner) is None) is valid


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


def test_add_records_jest_runner(runner: CliRunner, tmp_path: Path) -> None:
    path = tmp_path / "q.json"
    result = cli(
        runner, path, "add", "frontend/src/x.test.ts", "--runner", "jest", "--reason", "flaky", "--owner", "@web"
    )
    assert result.exit_code == 0, result.output
    entry = json.loads(path.read_text())["entries"][0]
    assert (entry["runner"], entry["id"]) == ("jest", "frontend/src/x.test.ts")


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
        ([raw_entry(expires=(TODAY + timedelta(days=40)).isoformat())], 1, "exceeds 30 days"),
        # expires before added
        ([raw_entry(expires=(TODAY - timedelta(days=1)).isoformat())], 1, "before added"),
        # expired beyond the grace period
        (
            [
                raw_entry(
                    added=(TODAY - timedelta(days=30)).isoformat(),
                    expires=(TODAY - timedelta(days=10)).isoformat(),
                )
            ],
            1,
            "remove or re-triage",
        ),
        # expired but within grace → warn, pass
        (
            [
                raw_entry(
                    added=(TODAY - timedelta(days=20)).isoformat(),
                    expires=(TODAY - timedelta(days=3)).isoformat(),
                )
            ],
            0,
            "remove within",
        ),
        # expired exactly grace days ago → last day of grace, warn without "within 0 days"
        (
            [
                raw_entry(
                    added=(TODAY - timedelta(days=27)).isoformat(),
                    expires=(TODAY - timedelta(days=7)).isoformat(),
                )
            ],
            0,
            "remove today — grace period ends",
        ),
        # forward compat: a runner without an adapter (and an unknown field) warn but pass
        ([raw_entry(runner="some-future-runner", future_field="x")], 0, "no enforcement adapter"),
        # a hand-edited future-dated entry must fail check, not sit active for years
        (
            [
                raw_entry(
                    runner="playwright",
                    id="playwright/e2e/x.spec.ts",
                    added=(TODAY + timedelta(days=365)).isoformat(),
                    expires=(TODAY + timedelta(days=395)).isoformat(),
                )
            ],
            1,
            "is in the future",
        ),
        # jest and playwright have enforcement adapters; valid entries pass clean
        ([raw_entry(runner="jest", id="frontend/src/x.test.ts")], 0, "OK"),
        ([raw_entry(runner="playwright", id="playwright/e2e/login.spec.ts::Login redirects home")], 0, "OK"),
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


def test_repo_quarantine_file_is_valid(runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core, "today_utc", WALL_CLOCK_TODAY_UTC)
    assert core.QUARANTINE_PATH.name == ".test_quarantine.json"
    result = runner.invoke(quarantine, ["check"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "expires_in_days, expected_state",
    [
        (30, None),
        (8, None),
        (7, core.EXPIRING_SOON),
        (0, core.EXPIRING_SOON),
        (-1, core.IN_GRACE),
        (-7, core.IN_GRACE),
        (-8, core.OVERDUE),
    ],
)
def test_collect_reports_only_entries_near_or_past_expiry(expires_in_days: int, expected_state: str | None) -> None:
    entry = make_entry(added=TODAY - timedelta(days=20), expires=TODAY + timedelta(days=expires_in_days))
    items = report.collect([entry], TODAY)
    assert [i.state for i in items] == ([expected_state] if expected_state else [])


def test_collect_orders_by_urgency_then_expiry() -> None:
    entries = [
        make_entry(id="soon", expires=TODAY + timedelta(days=2)),
        make_entry(id="overdue", added=TODAY - timedelta(days=25), expires=TODAY - timedelta(days=9)),
        make_entry(id="grace-later", added=TODAY - timedelta(days=10), expires=TODAY - timedelta(days=1)),
        make_entry(id="grace-earlier", added=TODAY - timedelta(days=12), expires=TODAY - timedelta(days=5)),
    ]
    assert [i.entry.id for i in report.collect(entries, TODAY)] == [
        "overdue",
        "grace-earlier",
        "grace-later",
        "soon",
    ]


@pytest.mark.parametrize(
    "owner, expected",
    [
        ("@team-devex", "@PostHog/team-devex"),
        ("team-devex", "@PostHog/team-devex"),
        ("@PostHog/team-devex", "@PostHog/team-devex"),
        ("@some-person", "@some-person"),
        ("data platform", "data platform"),
        ("", ""),
    ],
)
def test_mention_qualifies_team_slugs_only(owner: str, expected: str) -> None:
    assert report.mention(owner) == expected


def test_body_round_trips_the_state_it_embeds() -> None:
    entries = [
        make_entry(id="soon", expires=TODAY + timedelta(days=2)),
        make_entry(id="lapsed", added=TODAY - timedelta(days=20), expires=TODAY - timedelta(days=2)),
    ]
    items = report.collect(entries, TODAY)
    body = report.build_report(items, {}, core.DEFAULT_GRACE_DAYS).body
    assert report.read_states(body) == {"soon": core.EXPIRING_SOON, "lapsed": core.IN_GRACE}
    assert report.build_report(items, report.read_states(body), core.DEFAULT_GRACE_DAYS).comment is None


@pytest.mark.parametrize("body", ["", "no marker here", "<!-- quarantine-expiry-state: not json -->"])
def test_read_states_tolerates_a_body_without_usable_state(body: str) -> None:
    assert report.read_states(body) == {}


@pytest.mark.parametrize(
    "previous_states, expect_comment",
    [
        ({}, True),
        ({"lapsed": core.EXPIRING_SOON}, True),
        ({"lapsed": core.IN_GRACE}, False),
        ({"lapsed": core.OVERDUE}, False),
    ],
)
def test_comment_goes_out_only_when_an_entry_slips(previous_states: dict[str, str], expect_comment: bool) -> None:
    entry = make_entry(id="lapsed", added=TODAY - timedelta(days=20), expires=TODAY - timedelta(days=2))
    built = report.build_report(report.collect([entry], TODAY), previous_states, core.DEFAULT_GRACE_DAYS)
    assert (built.comment is not None) == expect_comment
    if expect_comment:
        assert "@PostHog/team-devex" in built.comment


@pytest.mark.parametrize(
    "ours, expected_number",
    [
        ([], None),
        ([False], None),
        ([True], 1),
        ([False, True], 2),
        ([True, False], 1),
    ],
)
def test_open_issue_claims_only_an_issue_it_wrote(
    monkeypatch: pytest.MonkeyPatch, ours: list[bool], expected_number: int | None
) -> None:
    digest = report.build_report([], {}, core.DEFAULT_GRACE_DAYS).body
    listed = [
        {"number": number, "body": digest if is_ours else "A person put the label on their own issue."}
        for number, is_ours in enumerate(ours, start=1)
    ]
    monkeypatch.setattr(report, "_gh", lambda *a, **k: json.dumps(listed))
    found = report.open_issue("PostHog/posthog")
    assert (found[0] if found else None) == expected_number


def test_open_issue_refuses_to_choose_between_two_digest_issues(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = report.build_report([], {}, core.DEFAULT_GRACE_DAYS).body
    listed = [{"number": 1, "body": digest}, {"number": 2, "body": digest}]
    monkeypatch.setattr(report, "_gh", lambda *a, **k: json.dumps(listed))
    with pytest.raises(RuntimeError, match=r"#1, #2"):
        report.open_issue("PostHog/posthog")


@pytest.mark.parametrize(
    "has_items, existing, expected_action, expected_subcommands, expected_preview",
    [
        (False, None, "nothing to report", [], "nothing to report"),
        (False, (7, ""), "closed #7", ["issue close"], "would close #7\n\n{close_comment}"),
        (True, None, "opened https://x/1", ["label create", "issue create"], "would open a new issue\n\n{body}"),
        (
            True,
            (7, ""),
            "updated #7 and notified owners",
            ["issue edit", "issue comment"],
            "would update #7 and notify owners\n\n{body}\n\n--- comment ---\n{comment}",
        ),
    ],
)
def test_preview_and_apply_agree_on_the_tracking_issue(
    monkeypatch: pytest.MonkeyPatch,
    has_items: bool,
    existing: tuple[int, str] | None,
    expected_action: str,
    expected_subcommands: list[str],
    expected_preview: str,
) -> None:
    calls: list[str] = []

    def fake_gh(*args: str, repo: str, stdin: str | None = None) -> str:
        calls.append(" ".join(args[:2]))
        return "https://x/1"

    monkeypatch.setattr(report, "_gh", fake_gh)
    entries = [make_entry(added=TODAY - timedelta(days=20), expires=TODAY - timedelta(days=2))] if has_items else []
    built = report.build_report(report.collect(entries, TODAY), {}, core.DEFAULT_GRACE_DAYS)
    assert report.preview(built, existing) == expected_preview.format(
        body=built.body, comment=built.comment, close_comment=report.CLOSE_COMMENT
    )
    assert report.apply(built, existing, "PostHog/posthog") == expected_action
    assert calls == expected_subcommands


def test_dry_run_previews_what_a_real_run_would_post(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = make_entry(id="lapsed", added=TODAY - timedelta(days=20), expires=TODAY - timedelta(days=2))
    already_reported = report.build_report(report.collect([entry], TODAY), {}, core.DEFAULT_GRACE_DAYS).body
    monkeypatch.setattr(report, "open_issue", lambda repo: (7, already_reported))
    monkeypatch.setattr(report, "_gh", lambda *a, **k: pytest.fail("a dry run must not write"))

    built, action = report.run([entry], TODAY, repo="PostHog/posthog", dry_run=True)
    assert built.comment is None
    assert action == f"would update #7\n\n{built.body}"
