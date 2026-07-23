from products.tasks.backend.logic.services.repo_commit_activity import _parse_log

_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40


def test_parse_log_extracts_commits_with_paths():
    stdout = (
        f"\x01{_SHA_A}\x1f2026-07-10T10:00:00+00:00\n"
        "products/signals/backend/models.py\n"
        "products/signals/backend/tasks.py\n"
        f"\x01{_SHA_B}\x1f2026-07-01T09:00:00+00:00\n"
        "posthog/models/user.py\n"
    )

    commits = _parse_log(stdout)

    assert [c.sha for c in commits] == [_SHA_A, _SHA_B]
    assert commits[0].paths == [
        "products/signals/backend/models.py",
        "products/signals/backend/tasks.py",
    ]
    assert commits[1].committed_at == "2026-07-01T09:00:00+00:00"


def test_parse_log_skips_malformed_records_and_handles_empty_output():
    assert _parse_log("") == []
    assert _parse_log("\x01broken-header-without-separators\nsome/path.py\n") == []
    # Shape validation: non-hex sha and non-ISO date records are dropped, so free-text
    # fields can't forge a record even if they smuggle the delimiters in.
    assert _parse_log("\x01not-a-sha\x1f2026-07-05T08:00:00+00:00\npath.py\n") == []
    assert _parse_log(f"\x01{_SHA_C}\x1fyesterday\npath.py\n") == []

    commits = _parse_log(f"\x01{_SHA_C}\x1f2026-07-05T08:00:00+00:00\n")
    assert len(commits) == 1
    assert commits[0].paths == []
