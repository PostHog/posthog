from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.domain_research import DomainResearch
from products.tasks.backend.facade.onboarding_brief import OnboardingFacts, build_opening_brief
from products.tasks.backend.facade.onboarding_prompt import BUNDLED_ONBOARDING_PROMPT, render_onboarding_prompt

SCRAPED = DomainResearch(outcome="scraped", url="northwind.example", markdown="# Northwind")


def _setup_facts(**overrides: object) -> OnboardingFacts:
    base: dict[str, object] = {
        "org_has_context": False,
        "research": SCRAPED,
        "has_events": True,
        "sources_enabled": ("error tracking",),
    }
    base.update(overrides)
    return OnboardingFacts(**base)  # type: ignore[arg-type]


class TestOpeningBrief(SimpleTestCase):
    @parameterized.expand(["not_configured", "unreachable", "busy"])
    def test_a_page_that_was_not_read_is_never_summarized_or_cited(self, outcome: str) -> None:
        brief = build_opening_brief(
            _setup_facts(research=DomainResearch(outcome=outcome, url="northwind.example"))  # type: ignore[arg-type]
        )

        joined = " ".join(brief)
        assert "Summarize what the company does" not in joined
        assert "Sources:" not in joined
        assert any("could not read their site" in line for line in brief)

    def test_no_research_at_all_reads_like_a_failed_read(self) -> None:
        brief = build_opening_brief(_setup_facts(research=None))

        joined = " ".join(brief)
        assert "Summarize what the company does" not in joined
        assert "Sources:" not in joined

    def test_a_read_page_is_summarized_and_cited(self) -> None:
        brief = build_opening_brief(_setup_facts())

        assert any("Summarize what the company does" in line for line in brief)
        assert brief[-1] == "Last line, exactly: Sources: northwind.example"

    def test_joining_an_existing_workspace_never_asks_about_the_company(self) -> None:
        brief = build_opening_brief(
            OnboardingFacts(
                org_has_context=True,
                signal_reports_waiting=3,
                other_members="Dana and 4 others",
                research=SCRAPED,
            )
        )

        joined = " ".join(brief)
        assert "Summarize what the company does" not in joined
        assert "Sources:" not in joined
        assert "Dana and 4 others" in joined

    @parameterized.expand(
        [
            ("no events offers to instrument, asking which repo", False, 0, "add PostHog to their codebase"),
            ("findings waiting offers to walk through one", True, 4, "walk them through"),
        ]
    )
    def test_the_offer_matches_the_situation(self, _name: str, has_events: bool, reports: int, expected: str) -> None:
        brief = build_opening_brief(_setup_facts(has_events=has_events, signal_reports_waiting=reports))

        offers = [line for line in brief if line.startswith("Offer to")]
        assert len(offers) == 1
        assert expected in offers[0]

    def test_nothing_is_offered_when_there_is_nothing_useful_to_offer(self) -> None:
        brief = build_opening_brief(_setup_facts(has_events=True, signal_reports_waiting=0))

        assert not any(line.startswith("Offer to") for line in brief)

    def test_a_project_with_no_events_is_never_promised_findings(self) -> None:
        brief = build_opening_brief(_setup_facts(has_events=False, sources_enabled=("error tracking",)))

        assert not any("findings will start landing" in line for line in brief)
        assert any("no PostHog data is arriving yet" in line for line in brief)


class TestBundledPromptRendering(SimpleTestCase):
    def test_rendering_leaves_no_placeholder_behind(self) -> None:
        brief = build_opening_brief(_setup_facts())

        rendered = render_onboarding_prompt(BUNDLED_ONBOARDING_PROMPT, brief=brief, homepage="# Northwind")

        assert "{{brief}}" not in rendered
        assert "{{homepage}}" not in rendered
        assert "Summarize what the company does" in rendered
        assert "# Northwind" in rendered
