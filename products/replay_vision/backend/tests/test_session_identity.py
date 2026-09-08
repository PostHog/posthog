from products.replay_vision.backend.temporal.activities.fetch_session_events import (
    _person_display_name,
    _person_organization,
)


class TestPersonOrganization:
    def test_prefers_the_most_specific_key_the_person_carries(self) -> None:
        # Both keys can sit on one person; a generic `company` is often self-reported free text where the
        # namespaced one comes from the product's own instrumentation.
        properties = {"company": "Typed By Hand", "org__name": "Customer Co"}

        assert _person_organization(properties) == "Customer Co"

    def test_falls_back_through_the_conventional_keys(self) -> None:
        assert _person_organization({"company_name": "Customer Co"}) == "Customer Co"

    def test_returns_none_when_no_key_holds_a_usable_value(self) -> None:
        # A blank or non-string value must read as unknown, so the prompt says so instead of naming an empty org.
        assert _person_organization({"org__name": "   ", "company": None, "organization": 42}) is None
        assert _person_organization({}) is None


class TestPersonDisplayName:
    def test_prefers_a_full_name_over_the_split_parts(self) -> None:
        assert _person_display_name({"name": "Rene Diaz", "first_name": "Rene"}) == "Rene Diaz"

    def test_joins_first_and_last_name_when_there_is_no_full_name(self) -> None:
        assert _person_display_name({"first_name": "Rene", "last_name": "Diaz"}) == "Rene Diaz"

    def test_uses_whichever_name_part_is_present(self) -> None:
        assert _person_display_name({"last_name": "Diaz"}) == "Diaz"

    def test_returns_none_when_the_person_carries_no_name(self) -> None:
        assert _person_display_name({"email": "rene@customer.example"}) is None
