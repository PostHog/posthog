from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.domain_research import DomainResearch
from products.tasks.backend.facade.onboarding_brief import (
    NO_FOLLOWUP,
    OnboardingFacts,
    build_followup,
    build_opening_brief,
    prose_list,
)
from products.tasks.backend.facade.onboarding_prompt import BUNDLED_ONBOARDING_PROMPT, render_onboarding_prompt

SCRAPED = DomainResearch(outcome="scraped", url="northwind.example", markdown="# Northwind")


def _setup_facts(**overrides: object) -> OnboardingFacts:
    base: dict[str, object] = {
        "org_has_context": False,
        "research": SCRAPED,
        "has_events": True,
        "sources_enabled": ("error tracking",),
        "sources_newly_enabled": True,
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

    def test_the_first_thing_they_read_says_where_they_are(self) -> None:
        brief = build_opening_brief(_setup_facts())

        assert brief[0] == "Open with: Welcome to PostHog Desktop."

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

    def test_joining_a_workspace_with_no_findings_yet_promises_none(self) -> None:
        brief = build_opening_brief(
            OnboardingFacts(org_has_context=True, signal_reports_waiting=0, other_members="Dana")
        )

        joined = " ".join(brief)
        assert "findings are waiting" not in joined
        assert not any(line.startswith("Offer to") for line in brief)
        assert "Dana" in joined

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

    def test_a_workspace_already_being_watched_is_never_told_we_just_turned_it_on(self) -> None:
        brief = build_opening_brief(_setup_facts(sources_newly_enabled=False))

        (status,) = [line for line in brief if "error tracking" in line]
        assert "you are watching error tracking" in status
        assert "turned on" not in status

    def test_the_message_names_a_few_sources_rather_than_listing_every_one(self) -> None:
        brief = build_opening_brief(
            _setup_facts(sources_enabled=("error tracking", "health checks", "support tickets", "Linear", "Sentry"))
        )

        (status,) = [line for line in brief if "you turned on" in line]
        assert "error tracking, health checks and 3 others" in status
        assert "Sentry" not in status


class TestProseList(SimpleTestCase):
    @parameterized.expand(
        [
            ((), None),
            (("a",), "a"),
            (("a", "b"), "a and b"),
            (("a", "b", "c"), "a, b and c"),
            (("a", "b", "c", "d"), "a, b and 2 others"),
            (("a", "b", "c", "d", "e"), "a, b and 3 others"),
        ]
    )
    def test_it_counts_the_tail_instead_of_naming_it(self, items: tuple[str, ...], expected: str | None) -> None:
        assert prose_list(items) == expected


class TestFollowup(SimpleTestCase):
    def test_setting_a_workspace_up_owes_it_the_company_context(self) -> None:
        assert "Save what the company does" in build_followup(_setup_facts())

    def test_joining_a_workspace_never_rewrites_the_context_it_joined(self) -> None:
        assert build_followup(OnboardingFacts(org_has_context=True)) == NO_FOLLOWUP


class TestBundledPromptRendering(SimpleTestCase):
    def test_rendering_leaves_no_placeholder_behind(self) -> None:
        facts = _setup_facts()

        rendered = render_onboarding_prompt(
            BUNDLED_ONBOARDING_PROMPT,
            brief=build_opening_brief(facts),
            followup=build_followup(facts),
            homepage="# Northwind",
            channel_id="0198f000-0000-7000-8000-000000000000",
        )

        assert "{{" not in rendered
        assert rendered.startswith("<onboarding_brief>")
        assert rendered.endswith("</onboarding_brief>")
        assert "Summarize what the company does" in rendered
        assert "# Northwind" in rendered
        assert "0198f000-0000-7000-8000-000000000000" in rendered

    def test_the_agent_only_instruction_stays_out_of_the_message_brief(self) -> None:
        facts = _setup_facts()

        brief = build_opening_brief(facts)

        assert not any("Save what the company does" in line for line in brief)
