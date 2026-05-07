"""Tests for the comment extractor and diff-based scanner."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comment_scanner import scan_diff_added_lines, scan_text  # noqa: E402


def test_python_line_comment_with_leak() -> None:
    source = textwrap.dedent("""\
        def foo():
            # See https://posthog.slack.com/archives/C012/p1234 for context
            return 1
    """)
    hits = scan_text("foo.py", source)
    assert len(hits) == 1
    assert hits[0].finding.category == "slack-permalink"
    assert hits[0].line == 2


def test_python_block_comment_with_leak() -> None:
    source = textwrap.dedent('''\
        """
        Reported via ZD-12345 from a customer.
        """
        x = 1
    ''')
    hits = scan_text("foo.py", source)
    assert any(h.finding.category == "zendesk-ticket-id" for h in hits)


def test_typescript_line_comment_with_leak() -> None:
    source = textwrap.dedent("""\
        function foo() {
          // ticket: https://posthog.zendesk.com/agent/tickets/9999
          return 1;
        }
    """)
    hits = scan_text("foo.ts", source)
    assert len(hits) == 1
    assert hits[0].finding.category == "zendesk-ticket-url"
    assert hits[0].line == 2


def test_javascript_block_comment_with_aws_key() -> None:
    source = textwrap.dedent("""\
        /*
         * AKIAIOSFODNN7EXAMPLE
         */
        const x = 1;
    """)
    hits = scan_text("foo.js", source)
    assert hits
    assert hits[0].finding.severity == "block"


def test_string_literals_not_scanned_as_comments() -> None:
    # The '#' inside a string literal should NOT be treated as a comment.
    # The pattern matcher might still find a leak in the string, but we
    # confine the scanner to comments only.
    source = textwrap.dedent("""\
        s = "https://posthog.slack.com/archives/C0/p1 # not a comment"
    """)
    hits = scan_text("foo.py", source)
    assert hits == []


def test_unsupported_extension_returns_no_hits() -> None:
    source = "# AKIAIOSFODNN7EXAMPLE"
    assert scan_text("binary.bin", source) == []


def test_non_comment_secrets_in_code_not_scanned() -> None:
    """Comment scanner only scans comments — code-level secrets are someone else's job (gitleaks)."""
    source = "API_KEY = 'AKIAIOSFODNN7EXAMPLE'\n"
    assert scan_text("foo.py", source) == []


def test_diff_only_added_lines_scanned() -> None:
    diff = textwrap.dedent("""\
        diff --git a/foo.py b/foo.py
        index 1234..5678 100644
        --- a/foo.py
        +++ b/foo.py
        @@ -1,3 +1,4 @@
         def foo():
        -    # old comment - https://posthog.slack.com/archives/C0/p1
        +    # new ZD-12345 reference
             return 1
    """)
    hits = scan_diff_added_lines(diff)
    # Only the new comment should surface; the deleted slack link must not.
    categories = {h.finding.category for h in hits}
    assert "zendesk-ticket-id" in categories
    assert "slack-permalink" not in categories


def test_diff_with_multiple_files() -> None:
    diff = textwrap.dedent("""\
        diff --git a/foo.py b/foo.py
        --- a/foo.py
        +++ b/foo.py
        @@ -1,1 +1,2 @@
         x = 1
        +# AKIAIOSFODNN7EXAMPLE
        diff --git a/bar.ts b/bar.ts
        --- a/bar.ts
        +++ b/bar.ts
        @@ -1,1 +1,2 @@
         const x = 1;
        +// see https://posthog.zendesk.com/agent/tickets/42
    """)
    hits = scan_diff_added_lines(diff)
    paths = {h.path for h in hits}
    assert paths == {"foo.py", "bar.ts"}


def test_diff_added_block_comment() -> None:
    diff = textwrap.dedent('''\
        diff --git a/foo.py b/foo.py
        --- a/foo.py
        +++ b/foo.py
        @@ -1,1 +1,4 @@
         x = 1
        +"""
        +ZD-12345 from customer
        +"""
    ''')
    hits = scan_diff_added_lines(diff)
    assert any(h.finding.category == "zendesk-ticket-id" for h in hits)


def test_empty_diff_returns_no_hits() -> None:
    assert scan_diff_added_lines("") == []


def test_diff_without_hunks_returns_no_hits() -> None:
    diff = "diff --git a/foo.py b/foo.py\nnew file mode 100644\n"
    assert scan_diff_added_lines(diff) == []


@pytest.mark.parametrize(
    "extension,prefix",
    [
        (".py", "#"),
        (".js", "//"),
        (".ts", "//"),
        (".go", "//"),
        (".rs", "//"),
        (".rb", "#"),
        (".sh", "#"),
        (".sql", "--"),
        (".scss", "//"),
    ],
)
def test_line_comment_prefixes(extension: str, prefix: str) -> None:
    source = f"x{prefix} https://posthog.zendesk.com/agent/tickets/1\n"
    hits = scan_text(f"foo{extension}", source)
    assert hits, f"no hits for {extension}"
