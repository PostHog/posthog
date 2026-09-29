from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized

from products.aeo.backend.facade.contracts import CitationGap, EngineAnswer
from products.web_analytics.backend.content_autopilot.lifecycle import ContentAutopilotLifecycleError
from products.web_analytics.backend.content_autopilot.opportunities import (
    MAX_DRAFTS_PER_RUN,
    dismiss_opportunity,
    draft_opportunities,
    page_ai_traffic,
    refresh_opportunities,
    score_gap,
    top_site_pages,
)
from products.web_analytics.backend.models import ContentAutopilotOpportunity, ContentAutopilotRun
from products.web_analytics.backend.test.content_autopilot_test_utils import (
    create_content_autopilot_opportunity,
    create_content_autopilot_profile,
    create_content_autopilot_run,
)

SITE_PAGES = [
    "https://example.com/",
    "https://example.com/pricing",
    "https://example.com/docs/session-replay",
    "https://example.com/docs/session-replay/privacy-controls",
    "https://example.com/blog/best-open-source-analytics-tools",
    "https://example.com/compare/best-adobe-analytics-alternatives",
    "https://example.com/compare/best-plausible-alternatives",
]


def _gap(
    prompt: str,
    *,
    checks: int = 9,
    cited_checks: int = 0,
    mentioned_checks: int = 0,
    engines: tuple[str, ...] = ("claude-web-search", "openai-web-search", "exa-answer"),
    engines_not_citing: tuple[str, ...] = ("claude-web-search", "openai-web-search", "exa-answer"),
    our_cited_urls: tuple[str, ...] = (),
) -> CitationGap:
    return CitationGap(
        prompt_id="0190a3b4-0000-0000-0000-000000000001",
        prompt_hash=f"hash-{prompt}",
        prompt_text=prompt,
        checks=checks,
        cited_checks=cited_checks,
        mentioned_checks=mentioned_checks,
        engines=engines,
        engines_not_citing=engines_not_citing,
        competitor_urls=("https://rival.example/replay",),
        competitor_domains=("rival.example",),
        engine_search_queries=("session replay tools",),
        our_cited_urls=our_cited_urls,
        latest_answers=(
            EngineAnswer(engine="claude-web-search", answer_text="Rival is great.", checked_at=timezone.now()),
        ),
        last_checked_at=timezone.now(),
    )


class TestOpportunityScoring(SimpleTestCase):
    def test_consistent_gaps_outrank_partial_and_thin_ones(self) -> None:
        consistent = score_gap(_gap("a"))
        partial = score_gap(
            _gap("b", cited_checks=4, engines_not_citing=("exa-answer",)),
        )
        thin = score_gap(_gap("c", checks=2))
        mentioned = score_gap(_gap("d", mentioned_checks=6))
        assert consistent > partial
        assert consistent > thin
        assert mentioned > consistent


@override_settings(AEO_TARGET_DOMAINS=["example.com"])
class TestRefreshOpportunities(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.profile = create_content_autopilot_profile(self.team)

    def _refresh(
        self, gaps: list[CitationGap], *, profile_id: str | None = None, page_urls: list[str] | None = SITE_PAGES
    ) -> list[ContentAutopilotOpportunity]:
        with patch(
            "products.web_analytics.backend.content_autopilot.opportunities.list_citation_gaps", return_value=gaps
        ):
            return refresh_opportunities(
                team=self.team, profile_id=profile_id or str(self.profile.id), page_urls=page_urls
            )

    def test_only_a_site_the_aeo_checks_track_gets_opportunities(self) -> None:
        other = create_content_autopilot_profile(self.team, domain="https://other.example")

        assert self._refresh([_gap("What is the best CRM?")], profile_id=str(other.id)) == []
        assert len(self._refresh([_gap("What is the best CRM?")])) == 1

    def test_an_empty_sitemap_still_limits_cited_pages_to_the_site_boundaries(self) -> None:
        self.profile.content_boundaries = ["/docs"]
        self.profile.save()

        opportunities = self._refresh(
            [
                _gap("Admin question", our_cited_urls=("https://example.com/admin/users",)),
                _gap("Docs question", our_cited_urls=("https://example.com/docs/replay",)),
            ],
            page_urls=[],
        )

        by_title = {opportunity.title: opportunity.target_url for opportunity in opportunities}
        assert by_title == {"Admin question": "", "Docs question": "https://example.com/docs/replay"}

    def test_recommends_improving_only_a_page_the_engines_cited(self) -> None:
        opportunities = self._refresh(
            [
                _gap("What is the best CRM for startups?"),
                _gap("How does session replay work?"),
                _gap("Is it cheap?", our_cited_urls=("https://example.com/pricing",)),
                _gap(
                    "Is it fast?",
                    our_cited_urls=("https://archive.example.com/pricing", "https://example.com/pricing?utm_source=ai"),
                ),
            ]
        )

        by_title = {opportunity.title: opportunity for opportunity in opportunities}
        assert by_title["What is the best CRM for startups?"].recommended_type == "new_content"
        assert by_title["How does session replay work?"].target_url == ""
        assert by_title["How does session replay work?"].recommended_type == "new_content"
        assert by_title["Is it cheap?"].recommended_type == "page_improvement"
        assert by_title["Is it cheap?"].target_url == "https://example.com/pricing"
        assert by_title["Is it fast?"].target_url == "https://example.com/pricing"
        assert "rival.example" in by_title["What is the best CRM for startups?"].evidence[0]["explanation"]
        assert (
            by_title["What is the best CRM for startups?"].gap["latest_answers"][0]["answer_text"] == "Rival is great."
        )

    def test_counts_ai_crawls_on_a_page_with_and_without_a_trailing_slash(self) -> None:
        for index, (path, host) in enumerate(
            [
                ("/pricing", None),
                ("/pricing/", "www.example.com"),
                ("/pricing/", None),
                ("/docs", None),
                ("/pricing", "other.example"),
            ]
        ):
            _create_event(
                team=self.team,
                event="$http_log",
                distinct_id=f"crawler-{index}",
                properties={
                    "$pathname": path,
                    "$raw_user_agent": "Mozilla/5.0 (compatible; GPTBot/1.2)",
                    **({"$host": host} if host else {}),
                },
            )
        flush_persons_and_events()

        traffic = page_ai_traffic(self.team, "https://example.com", ["/pricing"], include_hostless=True)
        shared = page_ai_traffic(self.team, "https://example.com", ["/pricing"], include_hostless=False)

        assert traffic["/pricing"]["ai_crawls"] == 3
        assert "/docs" not in traffic
        assert shared["/pricing"]["ai_crawls"] == 1

    def test_ranks_sitemap_pages_by_views_on_the_site_then_fills_with_shallow_pages(self) -> None:
        for path, views in [("/docs/session-replay", 3), ("/pricing/", 1), ("/not-in-sitemap", 5)]:
            for index in range(views):
                _create_event(
                    team=self.team,
                    event="$pageview",
                    distinct_id=f"visitor-{path}-{index}",
                    properties={"$host": "www.example.com", "$pathname": path},
                )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="other-site",
            properties={"$host": "app.other.example", "$pathname": "/docs/session-replay/privacy-controls"},
        )
        flush_persons_and_events()

        pages = top_site_pages(self.team, origin="https://example.com", page_urls=SITE_PAGES, limit=4)

        assert pages == [
            "https://example.com/docs/session-replay",
            "https://example.com/pricing",
            "https://example.com/",
            "https://example.com/docs/session-replay/privacy-controls",
        ]

    def test_refresh_keeps_dismissals_and_active_drafts_and_drops_gaps_that_closed(self) -> None:
        dismissed = create_content_autopilot_opportunity(self.team, self.profile, cluster_key="hash-dismissed")
        dismiss_opportunity(team=self.team, opportunity_id=str(dismissed.id))
        queued = create_content_autopilot_opportunity(
            self.team, self.profile, cluster_key="hash-queued", status=ContentAutopilotOpportunity.Status.QUEUED
        )
        queued.run = create_content_autopilot_run(self.team, self.profile)
        queued.save()
        stuck = create_content_autopilot_opportunity(
            self.team, self.profile, cluster_key="hash-stuck", status=ContentAutopilotOpportunity.Status.QUEUED
        )
        stuck.run = create_content_autopilot_run(
            self.team, self.profile, run_status=ContentAutopilotRun.RunStatus.CANCELED
        )
        stuck.save()
        closed = create_content_autopilot_opportunity(self.team, self.profile, cluster_key="hash-closed")
        closed_while_stuck = create_content_autopilot_opportunity(
            self.team, self.profile, cluster_key="hash-closed-stuck", status=ContentAutopilotOpportunity.Status.QUEUED
        )
        closed_while_stuck.run = stuck.run
        closed_while_stuck.save()

        self._refresh([_gap("dismissed"), _gap("queued"), _gap("stuck")])

        dismissed.refresh_from_db()
        queued.refresh_from_db()
        stuck.refresh_from_db()
        assert dismissed.status == ContentAutopilotOpportunity.Status.DISMISSED
        assert dismissed.title == "dismissed"
        assert queued.status == ContentAutopilotOpportunity.Status.QUEUED
        assert queued.title == "What is the best open source session replay tool?"
        assert (stuck.status, stuck.title) == (ContentAutopilotOpportunity.Status.NEW, "stuck")
        assert (
            not ContentAutopilotOpportunity.objects.for_team(self.team.id)
            .filter(id__in=[closed.id, closed_while_stuck.id])
            .exists()
        )


class TestDraftOpportunities(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.profile = create_content_autopilot_profile(self.team)

    def test_queues_opportunities_on_a_new_pending_run(self) -> None:
        opportunity = create_content_autopilot_opportunity(self.team, self.profile)

        run = draft_opportunities(
            team=self.team, profile_id=str(self.profile.id), opportunity_ids=[str(opportunity.id)], triggered_by_id=None
        )

        opportunity.refresh_from_db()
        assert run.run_status == ContentAutopilotRun.RunStatus.PENDING
        assert opportunity.status == ContentAutopilotOpportunity.Status.QUEUED
        assert opportunity.run_id == run.id

    @parameterized.expand(
        [
            ("too_many", MAX_DRAFTS_PER_RUN + 1, "up to"),
            ("none", 0, "at least one"),
        ]
    )
    def test_rejects_invalid_selection_sizes(self, _name: str, count: int, message: str) -> None:
        ids = [
            str(create_content_autopilot_opportunity(self.team, self.profile, cluster_key=f"hash-{index}").id)
            for index in range(count)
        ]
        with self.assertRaisesRegex(ContentAutopilotLifecycleError, message):
            draft_opportunities(
                team=self.team, profile_id=str(self.profile.id), opportunity_ids=ids, triggered_by_id=None
            )

    def test_rejects_opportunities_from_another_site_already_queued_or_dismissed(self) -> None:
        other_profile = create_content_autopilot_profile(self.team, domain="https://other.example")
        foreign = create_content_autopilot_opportunity(self.team, other_profile)
        with self.assertRaisesRegex(ContentAutopilotLifecycleError, "selected site"):
            draft_opportunities(
                team=self.team, profile_id=str(self.profile.id), opportunity_ids=[str(foreign.id)], triggered_by_id=None
            )

        queued = create_content_autopilot_opportunity(
            self.team, self.profile, cluster_key="queued", status=ContentAutopilotOpportunity.Status.QUEUED
        )
        queued.run = create_content_autopilot_run(self.team, self.profile)
        queued.save()
        with self.assertRaisesRegex(ContentAutopilotLifecycleError, "already being drafted"):
            draft_opportunities(
                team=self.team, profile_id=str(self.profile.id), opportunity_ids=[str(queued.id)], triggered_by_id=None
            )

        dismissed = create_content_autopilot_opportunity(
            self.team, self.profile, cluster_key="dismissed", status=ContentAutopilotOpportunity.Status.DISMISSED
        )
        with self.assertRaisesRegex(ContentAutopilotLifecycleError, "Dismissed"):
            draft_opportunities(
                team=self.team,
                profile_id=str(self.profile.id),
                opportunity_ids=[str(dismissed.id)],
                triggered_by_id=None,
            )
        assert ContentAutopilotRun.objects.for_team(self.team.id).count() == 1
