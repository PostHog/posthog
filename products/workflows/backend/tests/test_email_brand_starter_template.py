import json

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.models.email_brand import EmailBrand
from products.workflows.backend.services.email_brand_starter_template import (
    build_starter_design,
    build_starter_template,
)


def _cta_colors(design: dict) -> dict:
    content_column = design["body"]["rows"][1]["columns"][0]
    cta = next(content for content in content_column["contents"] if content["type"] == "button")
    return cta["values"]["buttonColors"]


class TestBuildStarterDesign(SimpleTestCase):
    @parameterized.expand(
        [
            ("near black", "#111111", "#ffffff"),
            ("saturated blue", "#1d4aff", "#ffffff"),
            ("dark green", "#0b6e4f", "#ffffff"),
            ("bright yellow", "#ffd400", "#000000"),
            ("orange", "#ff8800", "#000000"),
            ("near white", "#f5f5f5", "#000000"),
        ]
    )
    def test_cta_text_is_whichever_of_white_or_black_reads_on_the_primary(self, _name, primary, expected_text):
        colors = _cta_colors(build_starter_design(EmailBrand(primary_color=primary)))

        assert (colors["color"], colors["hoverColor"]) == (expected_text, expected_text)

    @parameterized.expand(
        [
            (
                "unlayer google font, any case",
                " montserrat ",
                "Montserrat, Arial, sans-serif",
                {
                    "label": "Montserrat",
                    "value": "'Montserrat',sans-serif",
                    "url": "https://fonts.googleapis.com/css?family=Montserrat:400,700",
                },
            ),
            (
                "unlayer system font",
                "Arial",
                "Arial, Helvetica, sans-serif",
                {"label": "Arial", "value": "arial,helvetica,sans-serif"},
            ),
            (
                "font unlayer does not ship",
                "Inter",
                "Inter, Arial, Helvetica, sans-serif",
                {"label": "Inter", "value": "Inter, Arial, Helvetica, sans-serif"},
            ),
        ]
    )
    def test_font_is_the_unlayer_default_only_when_the_brand_font_is_one(self, _name, family, stack, expected):
        design = build_starter_design(EmailBrand(font_family=family, font_stack=stack))

        assert design["body"]["values"]["fontFamily"] == expected

    @parameterized.expand(
        [
            ("output tag", "{{ person.properties.email }} Labs", "{{ person.properties.email }}"),
            ("unclosed block tag", "Acme {% if true %}", "{% if"),
        ]
    )
    def test_brand_name_reaches_the_email_as_text_not_liquid(self, _name, brand_name, liquid):
        starter = build_starter_template(EmailBrand(name=brand_name))

        assert liquid not in starter.subject
        assert liquid not in json.dumps(starter.design)
        assert "Labs" in starter.subject or "Acme" in starter.subject
