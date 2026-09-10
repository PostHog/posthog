from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.facade.onboarding_context import (
    COMPANY_HEADING,
    CompanyAnswer,
    company_answer_from,
    with_company_section,
)

ANSWER = CompanyAnswer(
    url="https://northwind.example/",
    description="Northwind Freight schedules shipments for regional trucking companies.",
    building="A driver mobile app.",
)


class TestCompanySection(SimpleTestCase):
    def test_a_repeated_write_replaces_the_section_rather_than_stacking_them(self) -> None:
        once = with_company_section("", ANSWER)
        twice = with_company_section(once, CompanyAnswer(description="Actually, they move furniture."))

        assert twice.count(COMPANY_HEADING) == 1
        assert "Actually, they move furniture." in twice
        assert "regional trucking companies" not in twice

    def test_context_written_before_this_survives(self) -> None:
        merged = with_company_section("## Team\n\nThree engineers.\n", ANSWER)

        assert "## Team" in merged
        assert "Three engineers." in merged
        assert merged.index("## Team") < merged.index(COMPANY_HEADING)

    def test_sections_written_after_this_one_survive_a_rewrite(self) -> None:
        first = with_company_section("", ANSWER)
        merged = with_company_section(f"{first}\n## Stack\n\nDjango.\n", CompanyAnswer(description="Freight."))

        assert "## Stack" in merged
        assert "Django." in merged
        assert "Freight." in merged

    def test_an_answer_that_opens_a_heading_cannot_end_the_section_early(self) -> None:
        # Their own words land in a markdown document, so a line starting with # would split it.
        merged = with_company_section("", CompanyAnswer(description="## Freight\nWe move things."))

        assert merged.count("## ") == 1
        assert "Freight" in merged
        assert "We move things." in merged

    @parameterized.expand(
        [
            ("nothing at all", "", "", "", True),
            ("whitespace only", "  ", "  ", "  ", True),
            ("a site alone", "northwind.example", "", "", False),
            ("a description alone", "", "Freight.", "", False),
            ("what they are building alone", "", "", "A driver app.", False),
        ]
    )
    def test_an_empty_step_is_not_treated_as_an_answer(
        self, _name: str, url: str, description: str, building: str, expected_blank: bool
    ) -> None:
        assert company_answer_from(url, description, building).is_blank is expected_blank

    def test_a_bare_domain_is_stored_as_a_url_an_agent_can_follow(self) -> None:
        assert company_answer_from("northwind.example", "", "").url == "https://northwind.example/"

    def test_a_site_that_is_not_a_url_is_dropped_rather_than_written_down(self) -> None:
        assert company_answer_from("not a website", "Freight.", "").url is None
