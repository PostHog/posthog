from products.tasks.backend.logic.services.repo_commit_activity import _parse_log


def test_parse_log_extracts_commits_with_paths():
    stdout = (
        "\x01aaa1111\x1fAlice\x1f1+alice@users.noreply.github.com\x1f2026-07-10T10:00:00+00:00\n"
        "products/signals/backend/models.py\n"
        "products/signals/backend/tasks.py\n"
        "\x01bbb2222\x1fBob\x1fbob@example.com\x1f2026-07-01T09:00:00+00:00\n"
        "posthog/models/user.py\n"
    )

    commits = _parse_log(stdout)

    assert [c.sha for c in commits] == ["aaa1111", "bbb2222"]
    assert commits[0].author_email == "1+alice@users.noreply.github.com"
    assert commits[0].paths == [
        "products/signals/backend/models.py",
        "products/signals/backend/tasks.py",
    ]
    assert commits[1].author_name == "Bob"
    assert commits[1].committed_at == "2026-07-01T09:00:00+00:00"


def test_parse_log_skips_malformed_records_and_handles_empty_output():
    assert _parse_log("") == []
    assert _parse_log("\x01broken-header-without-separators\nsome/path.py\n") == []

    commits = _parse_log("\x01ccc3333\x1fCarol\x1fcarol@example.com\x1f2026-07-05T08:00:00+00:00\n")
    assert len(commits) == 1
    assert commits[0].paths == []
