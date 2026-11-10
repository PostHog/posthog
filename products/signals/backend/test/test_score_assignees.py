import io
import sys
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from unittest.mock import patch

from owners_yaml.matcher import PatternMatcher

from products.signals.scripts.score_assignees import Commit, History, Member, Roster, load_history, main, rank_assignees

NOW = datetime(2026, 4, 15, tzinfo=UTC)
TARGET = "src/player/filter.py"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    (tmp_path / "src/player").mkdir(parents=True)
    (tmp_path / "src/other").mkdir()
    (tmp_path / "CODEOWNERS").write_text("/src/ @example-org/other-team\n/src/player/ @example-org/player-team\n")
    for path in [TARGET, "src/player/play.py", "src/other/api.py"]:
        (tmp_path / path).write_text("pass\n")
    return tmp_path


def member(
    login: str, team: str = "player-team", *, excluded_paths: tuple[str, ...] = (), active: bool = True
) -> Member:
    return Member(
        login=login,
        emails=(f"{login}@example.com",),
        teams=(f"example-org/{team}",),
        excluded_paths=excluded_paths,
        active=active,
    )


def commit(login: str, age: int, path: str = TARGET, serial: int = 0, subject: str = "fix: validate expiry") -> Commit:
    return Commit(
        sha=f"{login}-{age}-{serial}",
        email=f"{login}@example.com",
        authored_at=NOW - timedelta(days=age),
        subject=subject,
        paths=(path,),
    )


@pytest.mark.parametrize(
    "members,commits,expected",
    [
        (
            [member("former", "other-team"), member("owner")],
            [commit("former", 1, serial=i) for i in range(50)] + [commit("owner", 10)],
            "owner",
        ),
        ([member("old"), member("new")], [commit("old", 85, serial=i) for i in range(50)] + [commit("new", 2)], "new"),
        (
            [member("direct"), member("nearby")],
            [commit("direct", 20)] + [commit("nearby", 1, "src/player/play.py", i) for i in range(50)],
            "direct",
        ),
        (
            [member("former", "other-team"), member("maintainer")],
            [commit("former", 2), commit("maintainer", 3, "src/player/play.py")],
            None,
        ),
        ([member("quiet")], [], None),
        ([member("quiet"), member("other")], [], None),
        ([member("departed", excluded_paths=("src/player/",))], [commit("departed", 1)], None),
        ([member("inactive", active=False)], [commit("inactive", 1)], None),
        (
            [member("format"), member("owner")],
            [commit("format", 1, subject="chore: format code"), commit("owner", 3)],
            "owner",
        ),
    ],
)
def test_ranks_team_contributors_without_claiming_personal_ownership(
    repository: Path, members: list[Member], commits: list[Commit], expected: str | None
) -> None:
    result = rank_assignees(
        repository,
        TARGET,
        Roster(generated_at=NOW, members=tuple(members)),
        History(commits=tuple(commits), complete=True),
        NOW,
    )
    assert result.recommended_assignee is None
    assert result.agent_decision.case != "confirm_owner"
    if expected is not None:
        assert result.candidates[0].login == expected
        assert result.candidates[0].matches_owner_team
        assert not result.candidates[0].is_named_owner
        assert "unverified_responsibility" in result.agent_decision.reason_codes
    assert result.owners == ("@example-org/player-team",)
    assert result.scopes == (TARGET, "src/player")
    assert all(candidate.login != "former" for candidate in result.candidates)


@pytest.mark.parametrize("complete,roster_age", [(False, 0), (True, 8), (True, -1)])
def test_incomplete_evidence_does_not_recommend_an_assignee(repository: Path, complete: bool, roster_age: int) -> None:
    result = rank_assignees(
        repository,
        TARGET,
        Roster(generated_at=NOW - timedelta(days=roster_age), members=(member("owner"),)),
        History(commits=(commit("owner", 1),), complete=complete),
        NOW,
    )
    assert result.recommended_assignee is None
    assert result.warnings
    assert result.agent_decision.case == "needs_investigation"
    assert ("incomplete_history" in result.agent_decision.reason_codes) == (not complete)
    assert ("stale_roster" in result.agent_decision.reason_codes) == (roster_age != 0)


@pytest.mark.parametrize("exclude_file", [False, True])
def test_directory_uses_its_own_ownership_and_ignores_other_teams(repository: Path, exclude_file: bool) -> None:
    result = rank_assignees(
        repository,
        "src/player",
        Roster(
            generated_at=NOW,
            members=(member("owner", excluded_paths=(TARGET,) if exclude_file else ()), member("unrelated")),
        ),
        History(commits=(commit("owner", 5), commit("unrelated", 1, "src/other/api.py")), complete=True),
        NOW,
    )
    assert result.owners == ("@example-org/player-team",)
    assert result.recommended_assignee is None
    assert "unverified_responsibility" in result.agent_decision.reason_codes
    assert next(candidate for candidate in result.candidates if candidate.login == "unrelated").evidence_shas == ()
    if exclude_file:
        assert all(candidate.evidence == () for candidate in result.candidates)


@pytest.mark.parametrize("has_recent_work", [False, True])
@pytest.mark.parametrize("owner", ["@named", "@Named", "NAMED@example.com"])
def test_named_ownership_takes_precedence_over_team_contribution(
    repository: Path, has_recent_work: bool, owner: str
) -> None:
    (repository / "CODEOWNERS").write_text(f"/src/player/ @example-org/player-team {owner}\n")
    result = rank_assignees(
        repository,
        TARGET,
        Roster(generated_at=NOW, members=(member("contributor"), member("named", "other-team"))),
        History(
            commits=(commit("contributor", 1),) + ((commit("named", 30),) if has_recent_work else ()), complete=True
        ),
        NOW,
    )
    assert result.recommended_assignee == "named"
    assert result.agent_decision.case == "confirm_owner"
    assert result.agent_decision.reason_codes == ("named_owner_rule",)
    assert result.candidates[0].is_named_owner
    assert not result.candidates[0].matches_owner_team
    assert result.candidates[1].matches_owner_team
    assert not result.candidates[1].is_named_owner


@pytest.mark.parametrize(
    "rules,expected_owners,expected_pattern,expected_line",
    [
        ("* @other\n/src/player/ @named # current owner\n", ("@named",), "/src/player/", 2),
        ("/src/player/ @named\n/src/player/filter.py\n", (), "/src/player/filter.py", 2),
        ("*.py @named\n", ("@named",), "*.py", 1),
        ("player/ @named\n", ("@named",), "player/", 1),
        ("/player/ @named\n", (), None, None),
        ("src/* @named\n", (), None, None),
        ("src/**/filter.py @named\n", ("@named",), "src/**/filter.py", 1),
        ("/SRC/ @named\n", (), None, None),
        ("* @named\n!src/player/ @other\n", ("@named",), "*", 1),
        ("* @named\n/src/player/[f]ilter.py @other\n", ("@named",), "*", 1),
        ("* @named\n*** @other\n", ("@named",), "*", 1),
        ("* @named\n/src/player/ invalid-owner\n", ("@named",), "*", 1),
        (
            "# ignored\n\\#ignored @other\n/src/player/filter.py @named @other\n",
            ("@named", "@other"),
            "/src/player/filter.py",
            3,
        ),
    ],
)
def test_codeowners_rules_follow_github_precedence(
    repository: Path,
    rules: str,
    expected_owners: tuple[str, ...],
    expected_pattern: str | None,
    expected_line: int | None,
) -> None:
    (repository / "CODEOWNERS").write_text(rules)
    result = rank_assignees(
        repository,
        TARGET,
        Roster(generated_at=NOW, members=(member("named"),)),
        History(commits=(), complete=True),
        NOW,
    )
    assert result.owners == expected_owners
    assert result.ownership_pattern == expected_pattern
    assert result.ownership_line == expected_line
    assert result.ownership_source == ("CODEOWNERS" if expected_line else None)
    assert result.recommended_assignee == ("named" if "@named" in expected_owners else None)


@pytest.mark.parametrize(
    "locations",
    [
        (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"),
        ("CODEOWNERS", "docs/CODEOWNERS"),
        ("docs/CODEOWNERS",),
    ],
)
@pytest.mark.parametrize("first_matches", [False, True])
def test_codeowners_uses_only_the_first_file(repository: Path, locations: tuple[str, ...], first_matches: bool) -> None:
    (repository / "CODEOWNERS").unlink()
    for index, location in enumerate(locations):
        path = repository / location
        path.parent.mkdir(exist_ok=True)
        path.write_text(("* @named\n" if first_matches else "") if index == 0 else "* @other\n")
    result = rank_assignees(
        repository,
        TARGET,
        Roster(generated_at=NOW, members=(member("named"), member("other"))),
        History(commits=(), complete=True),
        NOW,
    )
    assert result.ownership_source == (locations[0] if first_matches else None)
    assert result.recommended_assignee == ("named" if first_matches else None)


@pytest.mark.parametrize(
    "team", ["example-org/player-team", "@Example-Org/Player-Team", "other-org/player-team", "player-team"]
)
def test_codeowners_team_membership_preserves_organization(repository: Path, team: str) -> None:
    result = rank_assignees(
        repository,
        TARGET,
        Roster(generated_at=NOW, members=(Member(login="owner", teams=(team,)),)),
        History(commits=(), complete=True),
        NOW,
    )
    assert bool(result.candidates) == (team.lower().lstrip("@") == "example-org/player-team")
    assert all(candidate.matches_owner_team and not candidate.is_named_owner for candidate in result.candidates)
    assert result.recommended_assignee is None


@pytest.mark.parametrize(
    "declaration,expected_owners,expected_source,expected_assignee",
    [
        (None, ("@codeowner",), "CODEOWNERS", "codeowner"),
        ("owners: ['@named']\n", ("@named",), "src/player/owners.yaml", "named"),
        ("owners: null\n", (), "src/player/owners.yaml", None),
        ("owners: []\n", ("@parent",), "src/owners.yaml", "parent"),
        ("owners: []\ninherit: false\n", ("@codeowner",), "CODEOWNERS", "codeowner"),
        (
            "owners: []\nrules:\n  - match: filter.py\n    owners: ['@named']\n",
            ("@named",),
            "src/player/owners.yaml",
            "named",
        ),
        ("owners: player-team\n", ("player-team",), "src/player/owners.yaml", None),
    ],
)
def test_owners_yaml_preserves_resolution_before_codeowners_fallback(
    repository: Path,
    declaration: str | None,
    expected_owners: tuple[str, ...],
    expected_source: str,
    expected_assignee: str | None,
) -> None:
    (repository / "CODEOWNERS").write_text("/src/player/ @codeowner\n")
    if declaration is not None:
        (repository / "src/owners.yaml").write_text("version: 1\nowners: ['@parent']\n")
        (repository / "src/player/owners.yaml").write_text(f"version: 1\n{declaration}")
    result = rank_assignees(
        repository,
        TARGET,
        Roster(
            generated_at=NOW,
            members=(Member(login="named", teams=("player-team",)), member("parent"), member("codeowner")),
        ),
        History(commits=(), complete=True),
        NOW,
    )
    assert result.owners == expected_owners
    assert result.ownership_source == expected_source
    assert result.recommended_assignee == expected_assignee
    if expected_owners == ("player-team",):
        assert result.candidates[0].login == "named"
        assert result.candidates[0].matches_owner_team
        assert not result.candidates[0].is_named_owner


def test_commit_is_not_counted_twice_and_unknown_authors_are_not_guessed(repository: Path) -> None:
    change = commit("owner", 1)
    roster = Roster(generated_at=NOW, members=(member("owner"),))
    single = rank_assignees(repository, TARGET, roster, History(commits=(change,), complete=True), NOW)
    repeated = rank_assignees(
        repository, TARGET, roster, History(commits=(change, change, commit("unknown", 1)), complete=True), NOW
    )
    assert single.candidates == repeated.candidates
    assert "1 git author email(s) have no explicit roster mapping" in repeated.warnings


def test_git_history_uses_original_author_date_and_reports_shallow_history(repository: Path) -> None:
    raw = "\x1esha\x002026-01-01T00:00:00+00:00\x00owner@example.com\x00fix: expiry\x00\x00\n" + TARGET + "\0"
    with patch("subprocess.check_output", side_effect=[raw, "true\n"]):
        history = load_history(repository, TARGET, NOW)
    assert not history.complete
    assert history.commits[0].paths == (TARGET,)
    assert history.commits[0].authored_at == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("path", ["../outside.py", ".", "missing.py"])
def test_path_must_be_inside_the_repository(repository: Path, path: str) -> None:
    with pytest.raises(ValueError, match="Path must exist inside"):
        rank_assignees(repository, path, Roster(generated_at=NOW, members=()), History(commits=(), complete=True), NOW)


def test_roster_rejects_ambiguous_email_identity() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        Roster(generated_at=NOW, members=(member("first"), Member(login="second", emails=("FIRST@example.com",))))


@pytest.mark.parametrize(
    "entry",
    [
        {"login": "owner", "active": "false"},
        {"login": "owner", "emails": "owner@example.com"},
        {"login": "owner", "teams": [None]},
        {"login": "owner", "unknown": True},
        {"login": "@owner"},
        {},
    ],
)
def test_roster_json_rejects_invalid_identity_fields(entry: dict) -> None:
    with pytest.raises(ValueError):
        Roster.from_json(json.dumps({"generated_at": NOW.isoformat(), "members": [entry]}))


@pytest.mark.parametrize("input_mode", ["single", "positional", "file", "stdin"])
@pytest.mark.parametrize("owned", [False, True])
def test_cli_reuses_ownership_and_preserves_per_path_results(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], input_mode: str, owned: bool
) -> None:
    rules = [f"{'/src/player/' if owned else '/unmatched/'} @example-org/player-team @owner"]
    rules.extend(f"/unrelated-{index}/ @other" for index in range(10))
    (repository / "CODEOWNERS").write_text("\n".join(rules))
    match_counts: Counter[str] = Counter()
    match_pattern = PatternMatcher.test

    def counted_match(matcher: PatternMatcher, path: str) -> bool:
        match_counts[path] += 1
        return match_pattern(matcher, path)

    roster = repository / "roster.json"
    roster.write_text(
        json.dumps(
            {
                "generated_at": NOW.isoformat(),
                "members": [{"login": "owner", "emails": ["owner@example.com"], "teams": ["example-org/player-team"]}],
            }
        )
    )
    paths = [TARGET, "missing.py", "../outside.py", "src/player"]
    arguments = ["score-assignees", "--repo", str(repository), "--roster", str(roster), "--now", NOW.isoformat()]
    if input_mode == "single":
        arguments += [TARGET]
    elif input_mode == "positional":
        arguments += paths
    else:
        paths_file = repository / "paths.json"
        paths_file.write_text(json.dumps(paths))
        arguments += ["--paths-file", "-" if input_mode == "stdin" else str(paths_file)]
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(paths)))
    monkeypatch.setattr(sys, "argv", arguments)
    with (
        patch("products.signals.scripts.score_assignees.git", return_value=str(repository)),
        patch(
            "products.signals.scripts.score_assignees.load_history",
            return_value=History(
                commits=tuple(commit("owner", 1, serial=index) for index in range(100)), complete=True
            ),
        ),
        patch.object(PatternMatcher, "test", counted_match),
    ):
        main()
    output = json.loads(capsys.readouterr().out)
    assert max(match_counts.values()) <= len(rules)
    if input_mode == "single":
        assert output["recommended_assignee"] == ("owner" if owned else None)
        assert output["schema_version"] == 4
    else:
        assert [result["path"] for result in output["results"]] == [TARGET, "src/player"]
        assert all(result["recommended_assignee"] == ("owner" if owned else None) for result in output["results"])
        assert [error["path"] for error in output["errors"]] == ["missing.py", "../outside.py"]


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired(["git", "log"], 60),
        subprocess.CalledProcessError(128, ["git", "log"]),
        OSError("git unavailable"),
    ],
)
def test_cli_caches_failed_history_scopes_and_continues_other_scopes(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: Exception
) -> None:
    roster = repository / "roster.json"
    roster.write_text(
        json.dumps(
            {
                "generated_at": NOW.isoformat(),
                "members": [{"login": "other", "emails": ["other@example.com"], "teams": ["example-org/other-team"]}],
            }
        )
    )
    paths = [TARGET, "src/player/play.py", "src/other/api.py"]
    monkeypatch.setattr(
        sys,
        "argv",
        ["score-assignees", "--repo", str(repository), "--roster", str(roster), "--now", NOW.isoformat(), *paths],
    )
    loads: Counter[str] = Counter()

    def history_for_scope(repo: Path, scope: str, now: datetime) -> History:
        loads[scope] += 1
        if scope == "src/player":
            raise failure
        return History(commits=(commit("other", 1, "src/other/api.py"),), complete=True)

    with (
        patch("products.signals.scripts.score_assignees.git", return_value=str(repository)),
        patch("products.signals.scripts.score_assignees.load_history", side_effect=history_for_scope),
    ):
        main()

    output = json.loads(capsys.readouterr().out)
    assert [result["path"] for result in output["results"]] == ["src/other/api.py"]
    assert output["results"][0]["candidates"][0]["login"] == "other"
    assert output["errors"] == [{"path": path, "error": str(failure)} for path in paths[:2]]
    assert loads == {"src/player": 1, "src": 1}


@pytest.mark.parametrize("manifest", [None, "product.yaml", "component.yaml"])
def test_unowned_paths_only_produce_provisional_candidates(repository: Path, manifest: str | None) -> None:
    target = repository / "unowned/file.py"
    target.parent.mkdir()
    target.write_text("pass\n")
    if manifest:
        (repository / "owners.yaml").write_text("version: 1\nowners: []\nalias_files: [component.yaml]\n")
        (target.parent / manifest).write_text("version: 1\nowners: ['@other']\n")
    result = rank_assignees(
        repository,
        "unowned/file.py",
        Roster(generated_at=NOW, members=(member("contributor"), member("other", "other-team"))),
        History(
            commits=(commit("contributor", 1, "unowned/file.py"), commit("other", 2, "unowned/file.py")), complete=True
        ),
        NOW,
    )
    assert [candidate.login for candidate in result.candidates] == ["contributor", "other"]
    assert result.recommended_assignee is None
    assert result.ownership_source is None
    assert result.scopes == ("unowned/file.py",)
    assert result.agent_decision.case == "needs_investigation"
    assert "no_declared_owner" in result.agent_decision.reason_codes
    assert result.agent_decision.max_pull_requests == 3
    assert all(not candidate.matches_owner_team and not candidate.is_named_owner for candidate in result.candidates)


@pytest.mark.parametrize("exclusion", ["none", "manual", "inactive"])
def test_inherited_owner_with_parent_activity_preserves_direct_investigation_leads(
    repository: Path, exclusion: str
) -> None:
    harness = repository / "src/player/harness"
    harness.mkdir()
    (harness / "runner.py").write_text("pass\n")
    roster = Roster(
        generated_at=NOW,
        members=(
            member("owner"),
            member(
                "contributor",
                "other-team",
                excluded_paths=("src/player/harness/",) if exclusion == "manual" else (),
                active=exclusion != "inactive",
            ),
        ),
    )
    result = rank_assignees(
        repository,
        "src/player/harness",
        roster,
        History(
            commits=(
                commit("owner", 1, "src/player/play.py"),
                commit("contributor", 2, "src/player/harness/runner.py"),
            ),
            complete=True,
        ),
        NOW,
    )
    assert result.ownership_source == "CODEOWNERS"
    assert result.ownership_pattern == "/src/player/"
    assert result.ownership_line == 2
    assert result.recommended_assignee is None
    assert result.agent_decision.case == "needs_investigation"
    assert "parent_only_evidence" in result.agent_decision.reason_codes
    assert [candidate.login for candidate in result.candidates] == ["owner"]
    assert ("ownership_conflict" in result.agent_decision.reason_codes) == (exclusion == "none")
    if exclusion == "none":
        assert [candidate.login for candidate in result.investigation_candidates] == ["contributor"]
        evidence = result.investigation_candidates[0].evidence[0]
        assert evidence.sha == "contributor-2-0"
        assert evidence.authored_at == NOW - timedelta(days=2)
        assert evidence.paths == ("src/player/harness/runner.py",)
        assert evidence.scope == "src/player/harness"
    else:
        assert result.investigation_candidates == ()
        assert [candidate.login for candidate in result.excluded] == ["contributor"]


def test_no_eligible_candidate_returns_unresolved(repository: Path) -> None:
    result = rank_assignees(
        repository, TARGET, Roster(generated_at=NOW, members=()), History(commits=(), complete=True), NOW
    )
    assert result.agent_decision.case == "unresolved"
    assert "no_candidates" in result.agent_decision.reason_codes
    assert result.recommended_assignee is None


def test_unknown_direct_identity_blocks_parent_only_recommendation(repository: Path) -> None:
    result = rank_assignees(
        repository,
        TARGET,
        Roster(generated_at=NOW, members=(member("owner"),)),
        History(commits=(commit("owner", 1, "src/player/play.py"), commit("unknown", 1)), complete=True),
        NOW,
    )
    assert result.agent_decision.case == "needs_investigation"
    assert "unmapped_direct_authors" in result.agent_decision.reason_codes
    assert result.recommended_assignee is None


@pytest.mark.parametrize("mode", ["tie", "multiple_teams"])
def test_ambiguous_direct_owners_require_investigation(repository: Path, mode: str) -> None:
    if mode == "multiple_teams":
        (repository / "CODEOWNERS").write_text("/src/player/ @example-org/player-team @example-org/other-team\n")
    result = rank_assignees(
        repository,
        TARGET,
        Roster(
            generated_at=NOW,
            members=(member("first"), member("second", "other-team" if mode == "multiple_teams" else "player-team")),
        ),
        History(commits=(commit("first", 1), commit("second", 2 if mode == "multiple_teams" else 1)), complete=True),
        NOW,
    )
    assert result.agent_decision.case == "needs_investigation"
    assert (
        "multiple_owner_teams" if mode == "multiple_teams" else "tied_candidates"
    ) in result.agent_decision.reason_codes
    assert result.recommended_assignee is None
