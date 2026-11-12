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
    CONTEXT_LINES,
    MAX_LITERAL_LENGTH,
    ExactCodeMatch,
    ExactCodeSearchResult,
    MatchedLine,
)

from products.messaging.backend.models.transactional_email_key import TransactionalEmailKey
from products.messaging.backend.services.code_email_source import CallSite, SourceDetection, rank_call_sites
from products.messaging.backend.tasks.tasks import detect_code_email_source_task


def _matched_line(number: int, sent: tuple[str, str]) -> MatchedLine:
    text, context = sent
    lines = context.split("\n")
    position = min(number - 1, CONTEXT_LINES)
    if lines[position : position + 1] != [text]:
        lines = [""] * (position - lines.index(text)) + lines
    return MatchedLine(number=number, text=text, context="\n".join(lines))


def _match(path: str, sent: tuple[str, str], *, repository: str = "acme/web", line: int = 12) -> ExactCodeMatch:
    return ExactCodeMatch(repository=repository, path=path, lines=(_matched_line(line, sent),))


_SDK_SEND = (
    "    template_key: 'welcome',",
    "await posthog.emails.send({\n    template_key: 'welcome',\n    to: user.email,\n})",
)
_RAW_SEND = (
    "requests.post(url, json={'template_key': 'welcome', 'to': to})",
    "url = f'{host}/api/projects/{project}/messaging/send/email/'\n"
    "requests.post(url, json={'template_key': 'welcome', 'to': to})",
)
_KEY_ONLY = ("WELCOME_KEY = 'welcome'", "WELCOME_KEY = 'welcome'")
_SUBJECT_BESIDE_ANOTHER_SEND = (
    "const subject = 'welcome'",
    "const subject = 'welcome'\nawait posthog.emails.send({\n    template_key: 'receipt',\n    subject,\n})",
)
_SUBJECT_IN_ANOTHER_SEND = (
    "await posthog.emails.send({ template_key: 'receipt', subject: 'welcome' })",
    "await posthog.emails.send({ template_key: 'receipt', subject: 'welcome' })",
)
_FALLBACK_KEY_IN_ANOTHER_SEND = (
    "    fallback_template_key: 'welcome',",
    "await posthog.emails.send({\n    template_key: 'receipt',\n    fallback_template_key: 'welcome',\n})",
)
_KEY_IN_AN_EVENT_AFTER_ANOTHER_SEND = (
    "posthog.capture('email sent', { template_key: 'welcome' })",
    "await posthog.emails.send({ template_key: 'receipt' })\nposthog.capture('email sent', { template_key: 'welcome' })",
)

_SEND_WITH_A_PARENTHESIS_IN_A_STRING = (
    "await posthog.emails.send({ subject: 'Hi :)', template_key: 'welcome' })",
    "await posthog.emails.send({ subject: 'Hi :)', template_key: 'welcome' })",
)
_RAW_SEND_WITH_A_CALL_BEFORE_THE_KEY = (
    "requests.post(f'{host}/send/email/', headers=headers(), json={'template_key': 'welcome'})",
    "requests.post(f'{host}/send/email/', headers=headers(), json={'template_key': 'welcome'})",
)
_KEY_LINE_REPEATED_ABOVE_THE_SEND = (
    "    template_key: 'welcome',",
    "const tags = {\n    template_key: 'welcome',\n}\nawait posthog.emails.send({\n    to: user.email,\n"
    "    template_key: 'welcome',\n})",
)

_KEY_IN_AN_EVENT_AFTER_A_SEND_WITH_A_PARENTHESIS_IN_A_STRING = (
    "posthog.capture('email sent', { template_key: 'welcome' })",
    "await posthog.emails.send({ template_key: 'receipt', subject: 'Step (1' })\n"
    "posthog.capture('email sent', { template_key: 'welcome' })",
)

_SEND_COMMENTED_OUT_ABOVE_THE_KEY = (
    "const props = { template_key: 'welcome' }",
    "// posthog.emails.send()\nconst props = { template_key: 'welcome' }",
)
_TRIPLE_QUOTED_BODY_BEFORE_THE_KEY = (
    '    template_key="welcome",',
    'posthog.emails.send(\n    body="""Hello (friend\nWelcome\n)""",\n    template_key="welcome",\n)',
)

_INLINE_COMMENT_WITH_A_PARENTHESIS_BEFORE_THE_KEY = (
    "    template_key: 'welcome',",
    "await posthog.emails.send({\n    to: user.email, // 1) recipient\n    template_key: 'welcome',\n})",
)


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
                                    _matched_line(12, _SDK_SEND),
                                    _matched_line(14, _SDK_SEND),
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
                "parenthesis_in_a_string_before_the_key",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/welcome.ts", _SEND_WITH_A_PARENTHESIS_IN_A_STRING)], complete=True
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
                "raw_send_with_a_call_before_the_key",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/welcome.ts", _RAW_SEND_WITH_A_CALL_BEFORE_THE_KEY)], complete=True
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
                "key_line_repeated_above_the_send",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/welcome.ts", _KEY_LINE_REPEATED_ABOVE_THE_SEND)], complete=True
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
                "triple_quoted_body_before_the_key",
                [
                    ExactCodeSearchResult(
                        matches=[_match("app/mailer.py", _TRIPLE_QUOTED_BODY_BEFORE_THE_KEY)], complete=True
                    )
                ],
                False,
                SourceDetection(
                    outcome="linked",
                    call_site=CallSite(repository="acme/web", path="app/mailer.py", line=12),
                    candidate_files=1,
                ),
            ),
            (
                "inline_comment_with_a_parenthesis_before_the_key",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/welcome.ts", _INLINE_COMMENT_WITH_A_PARENTHESIS_BEFORE_THE_KEY)],
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
                "only_a_constant",
                [ExactCodeSearchResult(matches=[_match("src/keys.ts", _KEY_ONLY)], complete=True)],
                False,
                SourceDetection(outcome="none", call_site=None, candidate_files=1),
            ),
            (
                "key_beside_a_send_of_another_key",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/receipt.ts", _SUBJECT_BESIDE_ANOTHER_SEND)], complete=True
                    )
                ],
                False,
                SourceDetection(outcome="none", call_site=None, candidate_files=1),
            ),
            (
                "key_in_a_send_of_another_key",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/receipt.ts", _SUBJECT_IN_ANOTHER_SEND)], complete=True
                    )
                ],
                False,
                SourceDetection(outcome="none", call_site=None, candidate_files=1),
            ),
            (
                "key_as_another_sends_fallback",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/receipt.ts", _FALLBACK_KEY_IN_ANOTHER_SEND)], complete=True
                    )
                ],
                False,
                SourceDetection(outcome="none", call_site=None, candidate_files=1),
            ),
            (
                "key_in_an_event_after_another_send",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/receipt.ts", _KEY_IN_AN_EVENT_AFTER_ANOTHER_SEND)], complete=True
                    )
                ],
                False,
                SourceDetection(outcome="none", call_site=None, candidate_files=1),
            ),
            (
                "key_in_an_event_after_a_send_with_a_parenthesis_in_a_string",
                [
                    ExactCodeSearchResult(
                        matches=[
                            _match(
                                "src/emails/receipt.ts", _KEY_IN_AN_EVENT_AFTER_A_SEND_WITH_A_PARENTHESIS_IN_A_STRING
                            )
                        ],
                        complete=True,
                    )
                ],
                False,
                SourceDetection(outcome="none", call_site=None, candidate_files=1),
            ),
            (
                "key_below_a_commented_out_send",
                [
                    ExactCodeSearchResult(
                        matches=[_match("src/emails/welcome.ts", _SEND_COMMENTED_OUT_ABOVE_THE_KEY)], complete=True
                    )
                ],
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
                            _match("app/test_mailer.py", _RAW_SEND),
                            _match("lib/mailer_spec.rb", _SDK_SEND),
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
        assert rank_call_sites(results, "welcome", shed=shed) == expected

    @parameterized.expand(
        [
            ("node", "    templateKey: 'welcome',", "await posthog.emails.send({"),
            ("python", "    template_key='welcome',", "posthog.emails.send("),
            ("json", '  "template_key": "welcome",', "curl -X POST $HOST/api/projects/1/messaging/send/email/"),
            ("php", "    'template_key' => 'welcome',", "$posthog->emails()->send(["),
            ("go", '    TemplateKey: "welcome",', "client.Emails().Send(ctx, posthog.SendEmailRequest{"),
            ("dotnet", '    TemplateKey = "welcome",', "await posthog.Emails.SendAsync(new SendEmailRequest {"),
            ("ruby_or_elixir", '  template_key: "welcome",', "PostHog.Emails.send("),
        ]
    )
    def test_links_the_template_key_as_each_sdk_spells_it(self, _name: str, text: str, send_call: str) -> None:
        results = [ExactCodeSearchResult(matches=[_match("src/mail", (text, f"{send_call}\n{text}"))], complete=True)]

        assert rank_call_sites(results, "welcome", shed=False).outcome == "linked"

    def test_a_detected_link_opens_the_line_on_the_default_branch(self) -> None:
        call_site = CallSite(repository="acme/web", path="src/emails/welcome email.ts", line=12)

        assert call_site.url == "https://github.com/acme/web/blob/HEAD/src/emails/welcome%20email.ts#L12"


_ONE_CALL_SITE = ExactCodeSearchResult(matches=[_match("src/emails/welcome.ts", _SDK_SEND)], complete=True)
_NOTHING = ExactCodeSearchResult(matches=[], complete=True)


@patch("products.messaging.backend.services.code_email_source.ph_scoped_capture")
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

    def _reported(self, scoped_capture: MagicMock) -> list[dict[str, Any]]:
        capture = scoped_capture.return_value.__enter__.return_value
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
        find.assert_called_once_with("welcome", deadline=None)
        assert self._reported(capture) == [
            {"team_id": self.team.id, "outcome": "linked", "attempt": 1, "installations": 1, "candidate_files": 1}
        ]
        retry.assert_not_called()

    @parameterized.expand([("linked", "https://gitlab.example.com/acme/web/-/blob/main/mail.ts"), ("unlinked", None)])
    def test_keeps_what_a_person_chose_while_it_searched(self, retry, find, _flag, capture, _name, person_link) -> None:
        def person_sets_the_link(_literal: str, **_: Any) -> ExactCodeSearchResult:
            TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).filter(id=self.key.id).update(
                source_url=person_link, source_origin="manual"
            )
            return _ONE_CALL_SITE

        find.side_effect = person_sets_the_link

        self._detect()

        self.key.refresh_from_db()
        assert (self.key.source_url, self.key.source_origin) == (person_link, "manual")
        assert [report["outcome"] for report in self._reported(capture)] == ["kept"]
        retry.assert_not_called()

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
    def test_searches_once_more_only_after_a_first_miss(
        self, retry, find, _flag, capture, _name, attempt, answer, outcome, retried
    ) -> None:
        if isinstance(answer, Exception):
            find.side_effect = answer
        else:
            find.return_value = answer

        self._detect(attempt)

        assert [(report["outcome"], report["attempt"]) for report in self._reported(capture)] == [(outcome, attempt)]
        assert retry.call_args_list == (
            [((), {"args": (self.team.id, str(self.key.id), 2), "countdown": 3000})] if retried else []
        )
        self.key.refresh_from_db()
        assert self.key.source_url is None

    @parameterized.expand(
        ["flag_off", "key_too_long_to_search", "key_spans_lines", "already_linked", "link_cleared", "no_github"]
    )
    def test_skips_the_search(self, retry, find, flag, capture, case) -> None:
        key = self.key
        if case == "flag_off":
            flag.return_value = False
        elif case == "key_too_long_to_search":
            key = self._key("k" * (MAX_LITERAL_LENGTH + 1))
        elif case == "key_spans_lines":
            key = self._key("pass\nword")
        elif case == "already_linked":
            TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).filter(id=key.id).update(
                source_url="https://example.com/mail.ts"
            )
        elif case == "link_cleared":
            TransactionalEmailKey.objects.for_team(self.team.id, canonical=True).filter(id=key.id).update(
                source_url=None, source_origin="manual"
            )
        else:
            Integration.objects.filter(team=self.team, kind="github").delete()

        self._detect(key=key)

        find.assert_not_called()
        assert self._reported(capture) == []
        retry.assert_not_called()
