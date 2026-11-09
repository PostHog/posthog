from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import Integration
from posthog.models.integration.github_code_search import (
    MAX_LITERAL_LENGTH,
    ExactCodeMatch,
    ExactCodeSearchResult,
    MatchedLine,
)

from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.services.code_email_source import CallSite, SourceDetection, rank_call_sites
from products.messaging.backend.tasks.tasks import detect_code_email_source_task


def _match(path: str, context: str, *, repository: str = "acme/web", line: int = 12) -> ExactCodeMatch:
    return ExactCodeMatch(repository=repository, path=path, lines=(MatchedLine(number=line, context=context),))


_SDK_SEND = "await posthog.emails.send({\n  template_key: 'welcome',\n  to: user.email,\n})"
_RAW_SEND = "requests.post(f'{host}/api/projects/{project}/messaging/send/email/', json={'template_key': 'welcome'})"
_KEY_ONLY = "WELCOME_KEY = 'welcome'"


class TestRankCallSites(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "one_sdk_call_site",
                [ExactCodeSearchResult(matches=[_match("src/emails/welcome.ts", _SDK_SEND)], complete=True)],
                False,
                SourceDetection(
                    outcome="linked",
                    call_site=CallSite(repository="acme/web", path="src/emails/welcome.ts", line=12),
                    candidate_files=1,
                ),
            ),
            (
                "two_call_sites_in_one_file",
                [
                    ExactCodeSearchResult(
                        matches=[
                            ExactCodeMatch(
                                repository="acme/web",
                                path="src/emails/welcome.ts",
                                lines=(
                                    MatchedLine(number=12, context=_SDK_SEND),
                                    MatchedLine(number=14, context=_SDK_SEND),
                                ),
                            )
                        ],
                        complete=True,
                    )
                ],
                False,
                SourceDetection(
                    outcome="linked",
                    call_site=CallSite(repository="acme/web", path="src/emails/welcome.ts", line=12),
                    candidate_files=1,
                ),
            ),
            (
                "call_sites_in_two_installations",
                [
                    ExactCodeSearchResult(matches=[_match("app/mailer.py", _RAW_SEND)], complete=True),
                    ExactCodeSearchResult(
                        matches=[_match("src/welcome.ts", _SDK_SEND, repository="acme-labs/api")], complete=True
                    ),
                ],
                False,
                SourceDetection(outcome="several", call_site=None, candidate_files=2),
            ),
            (
                "only_a_constant",
                [ExactCodeSearchResult(matches=[_match("src/keys.ts", _KEY_ONLY)], complete=True)],
                False,
                SourceDetection(outcome="none", call_site=None, candidate_files=1),
            ),
            (
                "test_paths_dropped",
                [
                    ExactCodeSearchResult(
                        matches=[
                            _match("src/emails/welcome.ts", _SDK_SEND),
                            _match("src/__tests__/welcome.ts", _SDK_SEND),
                            _match("src/emails/welcome.test.ts", _SDK_SEND),
                            _match("node_modules/@acme/mail/index.js", _SDK_SEND),
                        ],
                        complete=True,
                    )
                ],
                False,
                SourceDetection(
                    outcome="linked",
                    call_site=CallSite(repository="acme/web", path="src/emails/welcome.ts", line=12),
                    candidate_files=1,
                ),
            ),
            (
                "one_call_site_in_an_incomplete_search",
                [
                    ExactCodeSearchResult(matches=[_match("src/emails/welcome.ts", _SDK_SEND)], complete=True),
                    ExactCodeSearchResult(matches=[], complete=False),
                ],
                False,
                SourceDetection(outcome="incomplete", call_site=None, candidate_files=1),
            ),
            (
                "one_call_site_while_another_installation_was_shed",
                [ExactCodeSearchResult(matches=[_match("src/emails/welcome.ts", _SDK_SEND)], complete=True)],
                True,
                SourceDetection(outcome="budget", call_site=None, candidate_files=1),
            ),
        ]
    )
    def test_links_only_a_single_call_site_from_complete_searches(
        self, _name: str, results: list[ExactCodeSearchResult], shed: bool, expected: SourceDetection
    ) -> None:
        assert rank_call_sites(results, shed=shed) == expected

    def test_a_detected_link_opens_the_line_on_the_default_branch(self) -> None:
        call_site = CallSite(repository="acme/web", path="src/emails/welcome email.ts", line=12)

        assert call_site.url == "https://github.com/acme/web/blob/HEAD/src/emails/welcome%20email.ts#L12"


_ONE_CALL_SITE = ExactCodeSearchResult(matches=[_match("src/emails/welcome.ts", _SDK_SEND)], complete=True)
_NOTHING = ExactCodeSearchResult(matches=[], complete=True)


@patch("products.messaging.backend.services.code_email_source.posthoganalytics.capture")
@patch(
    "products.messaging.backend.services.code_email_source.posthoganalytics.feature_enabled",
    return_value=True,
)
@patch("products.messaging.backend.services.code_email_source.GitHubExactCodeSearch.find")
@patch.object(detect_code_email_source_task, "apply_async")
class TestDetectCodeEmailSource(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})
        self.key = self._key("welcome")

    def _key(self, key: str, **fields: Any) -> TransactionalEmailKey:
        return TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).create(
            team_id=self.team.id, key=key, hog_flow_id=uuid4(), **fields
        )

    def _detect(self, attempt: int = 1, key: TransactionalEmailKey | None = None) -> None:
        detect_code_email_source_task(self.team.id, str((key or self.key).id), attempt)

    def _reported(self, capture: MagicMock) -> list[dict[str, Any]]:
        return [
            call.kwargs["properties"]
            for call in capture.call_args_list
            if call.kwargs["event"] == "transactional email source detected"
        ]

    def test_links_the_one_call_site_and_reports_the_outcome(self, retry, find, _flag, capture) -> None:
        find.return_value = _ONE_CALL_SITE

        self._detect()

        self.key.refresh_from_db()
        assert (self.key.source_url, self.key.source_origin) == (
            "https://github.com/acme/web/blob/HEAD/src/emails/welcome.ts#L12",
            "detected",
        )
        find.assert_called_once_with("welcome")
        assert self._reported(capture) == [
            {"team_id": self.team.id, "outcome": "linked", "attempt": 1, "installations": 1, "candidate_files": 1}
        ]
        retry.assert_not_called()

    def test_keeps_a_link_a_person_set_while_it_searched(self, _retry, find, _flag, _capture) -> None:
        def person_links_the_file(_literal: str) -> ExactCodeSearchResult:
            TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).filter(id=self.key.id).update(
                source_url="https://gitlab.example.com/acme/web/-/blob/main/mail.ts"
            )
            return _ONE_CALL_SITE

        find.side_effect = person_links_the_file

        self._detect()

        self.key.refresh_from_db()
        assert (self.key.source_url, self.key.source_origin) == (
            "https://gitlab.example.com/acme/web/-/blob/main/mail.ts",
            "manual",
        )

    @parameterized.expand(
        [
            ("nothing_found", 1, _NOTHING, "none", True),
            ("nothing_found_again", 2, _NOTHING, "none", False),
            ("budget_shed", 1, GitHubEgressBudgetExhausted("shed"), "budget", True),
            ("github_error", 1, GitHubIntegrationError("bad credentials", status_code=401), "incomplete", True),
            (
                "several_call_sites",
                1,
                ExactCodeSearchResult(matches=[_match("a.ts", _SDK_SEND), _match("b.ts", _SDK_SEND)], complete=True),
                "several",
                False,
            ),
        ]
    )
    def test_searches_once_more_an_hour_later_only_after_a_first_miss(
        self, retry, find, _flag, capture, _name, attempt, answer, outcome, retried
    ) -> None:
        if isinstance(answer, Exception):
            find.side_effect = answer
        else:
            find.return_value = answer

        self._detect(attempt)

        assert [(report["outcome"], report["attempt"]) for report in self._reported(capture)] == [(outcome, attempt)]
        assert retry.call_args_list == (
            [((), {"args": (self.team.id, str(self.key.id), 2), "countdown": 3600})] if retried else []
        )
        self.key.refresh_from_db()
        assert self.key.source_url is None

    @parameterized.expand(["flag_off", "key_too_long_to_search", "already_linked", "no_github"])
    def test_skips_the_search(self, retry, find, flag, capture, case) -> None:
        key = self.key
        if case == "flag_off":
            flag.return_value = False
        elif case == "key_too_long_to_search":
            key = self._key("k" * (MAX_LITERAL_LENGTH + 1))
        elif case == "already_linked":
            TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).filter(id=key.id).update(
                source_url="https://example.com/mail.ts"
            )
        else:
            Integration.objects.filter(team=self.team, kind="github").delete()

        self._detect(key=key)

        find.assert_not_called()
        assert self._reported(capture) == []
        retry.assert_not_called()
