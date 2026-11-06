from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from unittest.mock import patch

from products.signals.scripts.score_assignees import Commit, History, Member, Roster, load_history, rank_assignees

NOW = datetime(2026, 4, 15, tzinfo=UTC)
TARGET = "src/player/filter.py"


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    (tmp_path / "src/player").mkdir(parents=True)
    (tmp_path / "src/other").mkdir()
    (tmp_path / "owners.yaml").write_text("version: 1\nowners: []\n")
    (tmp_path / "src/owners.yaml").write_text("version: 1\nowners: other-team\n")
    (tmp_path / "src/player/owners.yaml").write_text("version: 1\nowners: player-team\n")
    for path in [TARGET, "src/player/play.py", "src/other/api.py"]:
        (tmp_path / path).write_text("pass\n")
    return tmp_path


def member(
    login: str, team: str = "player-team", *, excluded_paths: tuple[str, ...] = (), active: bool = True
) -> Member:
    return Member(
        login=login, emails=(f"{login}@example.com",), teams=(team,), excluded_paths=excluded_paths, active=active
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
def test_selects_current_owner_with_nearest_recent_work(
    repository: Path, members: list[Member], commits: list[Commit], expected: str | None
) -> None:
    result = rank_assignees(
        repository,
        TARGET,
        Roster(generated_at=NOW, members=tuple(members)),
        History(commits=tuple(commits), complete=True),
        NOW,
    )
    assert result.recommended_assignee == expected
    assert (result.agent_decision.case == "confirm_owner") == (expected is not None)
    assert result.owners == ("player-team",)
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
    assert result.owners == ("player-team",)
    assert result.recommended_assignee == (None if exclude_file else "owner")
    assert next(candidate for candidate in result.candidates if candidate.login == "unrelated").evidence_shas == ()
    if exclude_file:
        assert all(candidate.evidence == () for candidate in result.candidates)


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


def test_unowned_paths_only_produce_provisional_candidates(repository: Path) -> None:
    target = repository / "unowned/file.py"
    target.parent.mkdir()
    target.write_text("pass\n")
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
    assert result.scopes == ("unowned/file.py",)
    assert result.agent_decision.case == "needs_investigation"
    assert "no_declared_owner" in result.agent_decision.reason_codes
    assert result.agent_decision.max_pull_requests == 3
    assert all(not candidate.matches_declared_ownership for candidate in result.candidates)


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
    assert result.ownership_is_inherited
    assert result.ownership_source == "src/player/owners.yaml"
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
        (repository / "src/player/owners.yaml").write_text("version: 1\nowners: [player-team, other-team]\n")
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
