from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from requests import ConnectTimeout, ReadTimeout

from products.tasks.backend.facade.domain_research import normalize_target, research_domain


class TestResearchDomain(SimpleTestCase):
    def test_an_invalid_address_literal_has_no_research_target(self) -> None:
        assert normalize_target("[1.2.3.4]") is None

    @parameterized.expand([("read_timeout", ReadTimeout), ("connect_timeout", ConnectTimeout)])
    def test_a_transport_failure_is_a_site_we_could_not_reach(self, _name: str, error: type[Exception]) -> None:
        with patch("products.tasks.backend.facade.domain_research.scrape", side_effect=error("boom")):
            research = research_domain("https://northwind.example/")

        assert research.outcome == "unreachable"
