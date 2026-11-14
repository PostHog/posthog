from datetime import datetime
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.today.backend.facade import contracts
from products.today.backend.logic.evidence import distinct_evidence_count, pick_evidence, signal_view
from products.today.backend.logic.signal_previews import body_paragraph, exception_chain, preview
from products.today.backend.logic.signal_text import SignalInput, detail, headline, meta
from products.today.backend.tests.factories import signal

SLACK_THREAD = "https://example.slack.com/archives/C1/p2"
ISSUE_URL = "https://github.com/example/web/issues/7"


class TestSignalViews(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "an error tracking issue",
                "New error tracking issue created - this particular exception was observed for the first time:\nValueError: `coupon_code`\n\n```\nstack\n```",
                "ValueError: coupon_code",
            ),
            (
                "a support ticket",
                "C: Two weekly invoices show a blank total for annual plans\\. They bill in euros.",
                "Two weekly invoices show a blank total for annual plans.",
            ),
            (
                "long scout prose",
                "The invoice export leaves out the tax column for archived plans. A nightly sync adds it back later.",
                "The invoice export leaves out the tax column for archived plans.",
            ),
            (
                "a github issue cited with a bare link",
                "GitHub issue #4521 (https://github.com/example/shop/issues/4521) reports that `Card was declined. Use another.` shows for `card_error`. It has no PR.",
                "GitHub issue #4521 reports that “Card was declined. Use another.” shows for card_error.",
            ),
            (
                "a long sentence, cut at its last clause",
                "Pressing Apply on the shipping rules settings screen does not keep the new rates, which means every edit to the rates is dropped and the merchant has to write to the help desk about it before the next billing run.",
                "Pressing Apply on the shipping rules settings screen does not keep the new rates, which means every edit to the rates is dropped and the merchant has…",
            ),
            (
                "a long sentence, never cut inside a quotation",
                "In the #shop-support thread about failed payments, one merchant reported that checkouts on the mobile app fail about a third of the time with “Gateway did not answer in time” errors.",
                "In the #shop-support thread about failed payments, one merchant reported that checkouts on the mobile app fail about a third of the time…",
            ),
            (
                "a pganalyze issue",
                "[info] orders-db — #42\nQuery #42 takes 95 ms on average (12345 calls in last 24h)",
                "Query #42 takes 95 ms on average (12,345 calls in last 24h)",
            ),
            (
                "an alert investigation",
                "Anomaly investigation for alert 'Orders dropped' on Orders (verdict: true positive).\nInsight: AB12 / id 1.\nPaid orders fell to 12 in the 09:00 hour on 2026-08-03. The detector fired before.",
                "Paid orders fell to 12 in the 09:00 hour on 3 Aug.",
            ),
            (
                "a day its month does not have, left as written",
                "Paid orders fell on 2026-02-30 and stayed low.",
                "Paid orders fell on 2026-02-30 and stayed low.",
            ),
            (
                "a date in year zero, left as written",
                "Paid orders fell on 0000-01-01 and stayed low.",
                "Paid orders fell on 0000-01-01 and stayed low.",
            ),
            (
                "a scout finding that ends in a thread link",
                f"A reviewer said the banner is too loud. Slack reply: {SLACK_THREAD}",
                "A reviewer said the banner is too loud.",
            ),
        ]
    )
    def test_writes_a_headline(self, _name: str, content: str, expected: str) -> None:
        assert headline(signal(content=content)) == expected

    @parameterized.expand(
        [
            ("a support ticket", signal(source_product="conversations", extra={"ticket_number": 1042}), "Ticket #1042"),
            (
                "a github issue",
                signal(source_product="github", source_type="issue", extra={"number": 7, "state": "open"}),
                "Issue #7",
            ),
            ("a scout finding on a file", signal(source_id="example/web:src/checkout/Address.tsx"), "Address.tsx"),
            ("a recording", signal(source_product="replay_vision", extra={"scanner_name": "Checkout friction"}), ""),
        ]
    )
    def test_names_only_the_identifier(self, _name: str, item: SignalInput, expected: str) -> None:
        assert meta(item) == expected

    @parameterized.expand(
        [
            (
                "a pganalyze issue, without its header line",
                signal(
                    source_product="pganalyze",
                    source_type="issue",
                    content="[info] orders-db — #42\nQuery #42 takes 95 ms on average (12345 calls in last 24h)",
                    extra={"server_name": "orders-db", "severity": "info"},
                ),
                ("Query #42 takes 95 ms on average (12,345 calls in last 24h)", "", ["orders-db", "info severity"]),
            ),
            (
                "a scout finding that cites a Slack thread, without the sentence that only points at it",
                signal(
                    content=f"The August 12 #shop-support discussion counted 2,316 merchants using saved carts over 30 days. Most were on the annual plan. The thread is available at {SLACK_THREAD}."
                ),
                (
                    "The August 12 #shop-support discussion counted 2,316 merchants using saved carts over 30 days.",
                    "Most were on the annual plan.",
                    [],
                ),
            ),
        ]
    )
    def test_opens_a_signal(self, _name: str, item: SignalInput, expected: tuple[str, str, list[str]]) -> None:
        found = detail(item)
        assert (found.lead, found.rest, found.facts) == expected

    def test_reads_a_stack_trace_as_a_chain_of_causes_at_the_teams_own_frames(self) -> None:
        content = "\n".join(
            [
                "New error tracking issue created - this particular exception was observed for the first time:",
                "JobError: the job failed with UploadError",
                "",
                "```",
                "JobError: the job failed with UploadError",
                "run in posthog/jobs/runner.py line 40",
                "start_upload in products/files/backend/upload.py line 12",
                "UploadError: Failed to upload",
                "put in products/files/backend/storage.py line 88",
                "send in boto3/client.py line 300",
                "```",
            ]
        )
        assert exception_chain(content) == [
            contracts.PreviewLine(text="  upload.py:12  start_upload", quiet=True),
            contracts.PreviewLine(text="Caused by UploadError: Failed to upload", quiet=False),
            contracts.PreviewLine(text="  storage.py:88  put", quiet=True),
        ]

    @parameterized.expand(
        [
            (
                "the paragraph under a title line",
                "Title line\nFirst paragraph.\n\nPart of #12.",
                None,
                "First paragraph.",
            ),
            (
                "the labelled section",
                "Title\n\n**Product area:** Billing\n\n**Issue:** The invoice is blank.\n\n**Resolution:** Fixed.",
                "Issue",
                "The invoice is blank.",
            ),
            ("nothing for a title alone", "Title only", None, None),
        ]
    )
    def test_finds_the_body(self, _name: str, content: str, label: str | None, expected: str | None) -> None:
        assert body_paragraph(content, label) == expected

    def test_shows_the_files_a_finding_names_in_its_own_folder(self) -> None:
        item = signal(
            source_id="example/shop:src/cards/Cards.tsx",
            content="`Cards.tsx` maps cards, and `cardsLogic.ts` caps them at `CARDS_MAX`.",
        )
        found = preview(item)
        assert found is not None
        assert [file.path for file in found.code] == ["src/cards/Cards.tsx", "src/cards/cardsLogic.ts"]

    @parameterized.expand(
        [
            (
                "nothing for a recording, which plays at once",
                signal(source_product="replay_vision", content="A button does nothing.", extra={"session_id": "s1"}),
                None,
            ),
            (
                "the query behind a pganalyze issue",
                signal(
                    source_product="pganalyze",
                    content="Query #1 takes 95 ms on average",
                    extra={"references": [{"kind": "Query", "queryText": "SELECT ... FROM orders"}]},
                ),
                ("Show the query", "", [contracts.PreviewLine(text="SELECT ... FROM orders", quiet=False)], None),
            ),
            (
                "the description of a GitHub issue",
                signal(
                    source_product="github",
                    source_type="issue",
                    content="Checkout drops the coupon\nThe cart forgets the coupon code after a refresh.\n\nPart of #12.",
                    extra={"html_url": "https://github.com/example/shop/issues/7", "number": 7, "state": "open"},
                ),
                ("Show the description", "The cart forgets the coupon code after a refresh.", [], "Open on GitHub"),
            ),
            (
                "the first message of a conversation without a subject",
                signal(
                    source_product="conversations",
                    source_type="ticket",
                    content="C: The invoice total is blank.\nT: We are looking into it.",
                ),
                ("Show the ticket", "The invoice total is blank. T: We are looking into it.", [], None),
            ),
            (
                "the lines after an alert finding",
                signal(
                    source_product="analytics",
                    source_type="anomaly_investigation",
                    content="Paid orders fell to 12 in the 09:00 hour.\nWhat the metric measures: paid orders per hour.",
                ),
                ("Show the finding", "What the metric measures: paid orders per hour.", [], None),
            ),
            (
                "the thread a Slack finding cites",
                signal(content=f"A teammate said the banner is too loud. {SLACK_THREAD}"),
                ("Show what the thread says", "", [], None),
            ),
        ]
    )
    def test_previews(
        self,
        _name: str,
        item: SignalInput,
        expected: tuple[str, str, list[contracts.PreviewLine], str | None] | None,
    ) -> None:
        found = preview(item)
        assert ((found.hint, found.text, found.block, found.link_label) if found else None) == expected

    @parameterized.expand(
        [
            (
                "replay vision seconds",
                {"session_id": "s1", "start_time": 108, "recording_start_time": "2026-10-02T12:15:23+00:00"},
                ("2026-10-02T12:17:06+00:00", "01:48", 103),
            ),
            (
                "session replay offset text",
                {"session_id": "s1", "start_time": "02:05", "session_start_time": "2026-10-02T12:00:00+00:00"},
                ("2026-10-02T12:02:00+00:00", "02:05", 120),
            ),
            ("a recording without a start time", {"session_id": "s1", "start_time": 108}, (None, "01:48", 103)),
        ]
    )
    def test_opens_a_recording_just_before_the_finding(
        self, _name: str, extra: dict[str, Any], expected: tuple[str | None, str, int]
    ) -> None:
        recording = signal_view(signal(source_product="replay_vision", extra=extra)).recording
        start_at, offset, seek_seconds = expected
        assert recording == contracts.RecordingTarget(
            session_id="s1",
            start_at=datetime.fromisoformat(start_at) if start_at else None,
            offset=offset,
            seek_seconds=seek_seconds,
        )

    @parameterized.expand(
        [
            (
                "a thread",
                f"A teammate reported it. Slack thread: {SLACK_THREAD}",
                contracts.PageLink(url=SLACK_THREAD, text="Open thread"),
            ),
            ("only prose", "A long finding without any link." * 10, None),
            ("a host that only ends in slack.com", "Slack thread: https://evilslack.com/archives/C1/p2", None),
        ]
    )
    def test_links_a_scout_finding_with(self, _name: str, content: str, expected: contracts.PageLink | None) -> None:
        assert signal_view(signal(content=content)).link == expected

    @parameterized.expand(
        [
            ("an issue", "issue", {}, contracts.PageLink(url=ISSUE_URL, text="Open issue")),
            (
                "a pull request",
                "pull_request",
                {"merged_at": None},
                contracts.PageLink(url=ISSUE_URL, text="Open pull request"),
            ),
            ("nothing for a link that is not http", "issue", {"html_url": "javascript:alert(1)"}, None),
            ("nothing for a link that does not parse", "issue", {"html_url": "https://[::1"}, None),
        ]
    )
    def test_links_a_github_signal_to(
        self, _name: str, source_type: str, extra: dict[str, Any], expected: contracts.PageLink | None
    ) -> None:
        item = signal(source_product="github", source_type=source_type, extra={"html_url": ISSUE_URL, **extra})
        assert signal_view(item).link == expected

    def test_shows_the_newest_signal_from_each_source_first(self) -> None:
        signals = [
            signal(signal_id="old-replay", source_product="replay_vision", timestamp="2026-09-01T00:00:00+00:00"),
            signal(signal_id="new-replay", source_product="replay_vision", timestamp="2026-09-03T00:00:00+00:00"),
            signal(signal_id="scout", timestamp="2026-08-01T00:00:00+00:00"),
        ]
        assert [picked.signal_id for picked in pick_evidence(signals, 2)] == ["new-replay", "scout"]

    def test_shows_one_row_for_several_checks_of_the_same_alert(self) -> None:
        signals = [
            signal(
                signal_id=check_id,
                source_product="analytics",
                source_id=check_id,
                timestamp=timestamp,
                extra={"alert_id": "orders-alert"},
            )
            for check_id, timestamp in (
                ("early-check", "2026-09-01T09:00:00+00:00"),
                ("late-check", "2026-09-01T09:40:00+00:00"),
            )
        ]
        assert [picked.signal_id for picked in pick_evidence(signals, 3)] == ["late-check"]
        assert distinct_evidence_count(signals) == 1
