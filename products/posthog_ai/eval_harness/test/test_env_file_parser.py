from __future__ import annotations

from pathlib import Path

import pytest

from products.posthog_ai.eval_harness.harness.env_preflight import parse_env_file

PEM_ESCAPED = 'KEY="-----BEGIN PRIVATE KEY-----\\nMIIEvQIBADANBg\\n-----END PRIVATE KEY-----\\n"'
PEM_MULTILINE = 'KEY="-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----\n"'
PEM_DECODED = "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----\n"


@pytest.mark.parametrize(
    "content, expected",
    [
        pytest.param("KEY=value", {"KEY": "value"}, id="bare_assignment"),
        pytest.param("export KEY=value", {"KEY": "value"}, id="export_prefix"),
        pytest.param("KEY = spaced ", {"KEY": "spaced"}, id="whitespace_stripped"),
        pytest.param("# comment\n\nKEY=value\n", {"KEY": "value"}, id="comments_and_blank_lines_skipped"),
        pytest.param("KEY=value # trailing comment", {"KEY": "value"}, id="unquoted_inline_comment_stripped"),
        pytest.param("KEY='single # quoted'", {"KEY": "single # quoted"}, id="single_quotes_keep_hashes"),
        pytest.param("KEY='literal\\nvalue'", {"KEY": "literal\\nvalue"}, id="single_quotes_skip_escape_decoding"),
        pytest.param('KEY="a\\tb\\"c\\\\d"', {"KEY": 'a\tb"c\\d'}, id="double_quotes_decode_escapes"),
        pytest.param(PEM_ESCAPED, {"KEY": PEM_DECODED}, id="escaped_pem_becomes_multiline"),
        pytest.param(PEM_MULTILINE, {"KEY": PEM_DECODED}, id="quoted_multiline_pem"),
        pytest.param("KEY=first\nKEY=second", {"KEY": "second"}, id="later_assignment_wins"),
        pytest.param("not an assignment\nKEY=value", {"KEY": "value"}, id="malformed_lines_skipped"),
        pytest.param("KEY=", {"KEY": ""}, id="empty_value"),
    ],
)
def test_parse_env_file(tmp_path: Path, content: str, expected: dict[str, str]) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(content)
    assert parse_env_file(env_file) == expected
