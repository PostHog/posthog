import base64
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError, Integration
from posthog.models.integration.github_code_search import (
    MAX_MATCHED_LINES_PER_FILE,
    ExactCodeMatch,
    GitHubExactCodeSearch,
    MatchedLine,
)


def _github(account_type: str = "Organization") -> GitHubIntegration:
    integration = Integration(
        kind="github",
        integration_id="42",
        config={"account": {"name": "acme", "type": account_type}},
        sensitive_config={"access_token": "ACCESS_TOKEN"},
    )
    return GitHubIntegration(integration, source="test", priority=Priority.BATCH)


def _search_item(repository: str, path: str) -> dict[str, Any]:
    return {"path": path, "repository": {"full_name": repository}}


def _contents(text: str | bytes, sha: str) -> MagicMock:
    encoded = text if isinstance(text, bytes) else text.encode()
    payload = {"sha": sha, "size": len(encoded), "encoding": "base64", "content": base64.b64encode(encoded).decode()}
    return MagicMock(status_code=200, json=MagicMock(return_value=payload))


class TestGitHubExactCodeSearch(SimpleTestCase):
    def _search(
        self,
        github: GitHubIntegration,
        literal: str,
        search_body: dict[str, Any],
        files: dict[str, MagicMock | Exception],
        deadline: float | None = None,
    ) -> tuple[Any, list[dict[str, Any]]]:
        requests_made: list[dict[str, Any]] = []

        def api_request(method: str, path: str, **kwargs: Any) -> MagicMock:
            requests_made.append({"path": path, **kwargs})
            if path == "/search/code":
                return MagicMock(status_code=200, json=MagicMock(return_value=search_body))
            response = files[path]
            if isinstance(response, Exception):
                raise response
            return response

        with patch.object(github, "api_request", side_effect=api_request):
            result = GitHubExactCodeSearch(github).find(literal, deadline=deadline)
        return result, requests_made

    def test_keeps_only_files_with_the_exact_literal(self) -> None:
        sender_lines = [
            "import { posthog } from './posthog'",
            "// sends password reset mail",
            "await posthog.emails.send({",
            "  templateKey: 'password-reset',",
            "})",
            "const legacy = 'password-reset-v2'",
            'const other = "password-reset"',
        ]
        near_misses = "\n".join(["PASSWORD-RESET", "password_reset", "password reset", "xpassword-reset"])
        result, requests_made = self._search(
            _github(),
            "password-reset",
            {
                "total_count": 2,
                "incomplete_results": False,
                "items": [_search_item("acme/web", "src/send.ts"), _search_item("acme/web", "docs/q&a #1.md")],
            },
            {
                "/repos/acme/web/contents/src/send.ts": _contents("\n".join(sender_lines), "sha-send"),
                "/repos/acme/web/contents/docs/q%26a%20%231.md": _contents(near_misses, "sha-notes"),
            },
        )

        assert result.matches == [
            ExactCodeMatch(
                repository="acme/web",
                path="src/send.ts",
                lines=(
                    MatchedLine(number=4, text=sender_lines[3], context="\n".join(sender_lines)),
                    MatchedLine(number=7, text=sender_lines[6], context="\n".join(sender_lines[1:])),
                ),
            )
        ]
        assert result.complete is True
        assert requests_made[0]["params"]["q"] == '"password-reset" org:acme'

    def test_scopes_a_personal_account_with_the_user_qualifier(self) -> None:
        _, requests_made = self._search(
            _github(account_type="User"), "welcome", {"total_count": 0, "incomplete_results": False, "items": []}, {}
        )

        assert requests_made[0]["params"]["q"] == '"welcome" user:acme'

    @parameterized.expand(
        [
            ("github_says_incomplete", {"total_count": 1, "incomplete_results": True}, 200),
            ("more_results_than_read", {"total_count": 5, "incomplete_results": False}, 200),
            ("candidate_gone", {"total_count": 1, "incomplete_results": False}, 404),
            ("candidate_not_utf8", {"total_count": 1, "incomplete_results": False}, 200, b"caf\xe9"),
        ]
    )
    def test_reports_an_incomplete_search(
        self, _name: str, search_body: dict[str, Any], file_status: int, raw: bytes = b"send('welcome')"
    ) -> None:
        file_response = _contents(raw, "sha-1")
        file_response.status_code = file_status
        result, _ = self._search(
            _github(),
            "welcome",
            {**search_body, "items": [_search_item("acme/web", "a.py")]},
            {"/repos/acme/web/contents/a.py": file_response},
        )

        assert result.complete is False

    @parameterized.expand([("deadline_passed",), ("read_shed",)])
    def test_keeps_what_it_read_when_reading_stops_early(self, case: str) -> None:
        files: dict[str, MagicMock | Exception] = {
            "/repos/acme/web/contents/a.py": _contents("send('welcome')", "sha-1")
        }
        if case == "read_shed":
            files["/repos/acme/web/contents/b.py"] = GitHubEgressBudgetExhausted("shed")
        with patch("posthog.models.integration.github_code_search.time.monotonic", side_effect=[0.0, 10.0]):
            result, requests_made = self._search(
                _github(),
                "welcome",
                {
                    "total_count": 2,
                    "incomplete_results": False,
                    "items": [_search_item("acme/web", "a.py"), _search_item("acme/web", "b.py")],
                },
                files,
                deadline=5.0 if case == "deadline_passed" else None,
            )

        read = ["/search/code", "/repos/acme/web/contents/a.py"]
        assert [request["path"] for request in requests_made] == (
            read if case == "deadline_passed" else [*read, "/repos/acme/web/contents/b.py"]
        )
        assert [match.path for match in result.matches] == ["a.py"]
        assert result.complete is False

    @parameterized.expand([("at_the_cap", 0, True), ("over_the_cap", 1, False)])
    def test_keeps_the_first_matched_lines_of_a_crowded_file(self, _name: str, extra: int, complete: bool) -> None:
        result, _ = self._search(
            _github(),
            "welcome",
            {"total_count": 1, "incomplete_results": False, "items": [_search_item("acme/web", "a.py")]},
            {"/repos/acme/web/contents/a.py": _contents("welcome\n" * (MAX_MATCHED_LINES_PER_FILE + extra), "sha-1")},
        )

        assert [line.number for line in result.matches[0].lines] == list(range(1, MAX_MATCHED_LINES_PER_FILE + 1))
        assert result.complete is complete

    def test_raises_when_github_refuses_the_search(self) -> None:
        github = _github()
        with patch.object(github, "api_request", return_value=MagicMock(status_code=403, text="forbidden")):
            with self.assertRaises(GitHubIntegrationError):
                GitHubExactCodeSearch(github).find("welcome")

    @parameterized.expand([("blank", "  "), ("over_github_query_limit", "k" * 255), ("two_lines", "pass\nword")])
    def test_rejects_a_literal_github_cannot_search(self, _name: str, literal: str) -> None:
        github = _github()
        with patch.object(github, "api_request") as api_request:
            with self.assertRaises(ValueError):
                GitHubExactCodeSearch(github).find(literal)
        api_request.assert_not_called()
