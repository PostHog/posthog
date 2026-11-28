from django.test import SimpleTestCase

from parameterized import parameterized

from products.user_journeys.backend.facade.contracts import ElementClickStep, PageviewStep
from products.user_journeys.backend.facade.enums import UrlMatching
from products.user_journeys.backend.presentation.serializers import (
    CreateJourneyInputSerializer,
    UpdateJourneyInputSerializer,
)

PAGEVIEW = {"type": "pageview", "url": "https://example.com/pricing"}
CLICK = {"type": "element_click", "selector": "button.signup"}


class TestJourneyStepsValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("one_step", [PAGEVIEW]),
            ("too_many_steps", [PAGEVIEW] * 21),
            ("not_a_list", PAGEVIEW),
            ("step_not_an_object", [PAGEVIEW, "https://example.com"]),
            ("missing_type", [PAGEVIEW, {"url": "https://example.com"}]),
            ("unknown_type", [PAGEVIEW, {"type": "scroll", "url": "https://example.com"}]),
            ("pageview_without_url", [PAGEVIEW, {"type": "pageview"}]),
            ("click_without_selector", [PAGEVIEW, {"type": "element_click", "text": "Sign up"}]),
            ("click_with_blank_selector", [PAGEVIEW, {**CLICK, "selector": ""}]),
            ("unknown_url_matching", [{**PAGEVIEW, "url_matching": "starts_with"}, CLICK]),
            ("invalid_regex", [{**PAGEVIEW, "url": "(unclosed", "url_matching": "regex"}, CLICK]),
            ("field_of_the_other_step_type", [{**PAGEVIEW, "selector": "button"}, CLICK]),
            ("unknown_field", [PAGEVIEW, {**CLICK, "xpath": "//button"}]),
        ]
    )
    def test_rejects_bad_steps_on_create_and_update(self, _name: str, steps: object) -> None:
        for serializer_class, base in (
            (CreateJourneyInputSerializer, {"name": "Sign up"}),
            (UpdateJourneyInputSerializer, {}),
        ):
            serializer = serializer_class(data={**base, "steps": steps})
            assert not serializer.is_valid()
            assert "steps" in serializer.errors

    def test_parses_mixed_steps_into_typed_contracts(self) -> None:
        serializer = CreateJourneyInputSerializer(
            data={
                "name": "Sign up",
                "steps": [
                    {**PAGEVIEW, "url_matching": "contains"},
                    {**CLICK, "text": "Sign up", "url": "/pricing", "url_matching": "contains"},
                ],
            }
        )
        assert serializer.is_valid(), serializer.errors
        data = serializer.validated_data
        assert data.steps == [
            PageviewStep(url="https://example.com/pricing", url_matching=UrlMatching.CONTAINS),
            ElementClickStep(
                selector="button.signup", text="Sign up", url="/pricing", url_matching=UrlMatching.CONTAINS
            ),
        ]
        assert data.conversion_window_minutes == 30
        assert data.source == "manual"

    @parameterized.expand([("zero", 0), ("longer_than_a_day", 24 * 60 + 1)])
    def test_rejects_conversion_window_out_of_range(self, _name: str, minutes: int) -> None:
        serializer = UpdateJourneyInputSerializer(data={"conversion_window_minutes": minutes})
        assert not serializer.is_valid()
        assert "conversion_window_minutes" in serializer.errors

    def test_update_rejects_null_steps(self) -> None:
        serializer = UpdateJourneyInputSerializer(data={"steps": None})
        assert not serializer.is_valid()
        assert "steps" in serializer.errors
