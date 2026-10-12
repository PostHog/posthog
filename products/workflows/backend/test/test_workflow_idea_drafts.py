from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.facade.contracts import IdeaDraftSpec, IdeaEmail
from products.workflows.backend.services.workflow_idea_drafts import (
    SITE_PLACEHOLDER,
    build_idea_definition,
    find_site_url,
    new_idea_from_draft,
)


def _email(subject: str, path: str = "/") -> IdeaEmail:
    return IdeaEmail(
        subject=subject,
        preheader="A short preview",
        heading="Pick up where you left off",
        paragraphs=["Your trial is ready.", "Pick a plan to keep your work <safe>."],
        button_text="Choose a plan",
        button_path=path,
    )


def _spec(*, site_url: str | None = "https://app.example.com", waits: list[str] | None = None) -> IdeaDraftSpec:
    return IdeaDraftSpec(
        trigger_event="trial started",
        goal_events=["plan purchased", "plan upgraded"],
        waits=waits or ["1h", "2d"],
        emails=[_email("Your trial is ready", "/pricing"), _email("Still deciding?")],
        sender_name="Example & Co",
        site_url=site_url,
        campaign="trial-nudge",
        once_per_person_days=14,
    )


def _emails(definition: dict) -> list[dict]:
    return [a for a in definition["actions"] if a["type"] == "function_email"]


class TestWorkflowIdeaDrafts(SimpleTestCase):
    def test_definition_limits_entry_and_stops_on_the_goal(self):
        definition = build_idea_definition(_spec())

        assert definition["trigger_masking"] == {"hash": "{person.id}", "ttl": 14 * 24 * 60 * 60}
        assert definition["exit_condition"] == "exit_on_conversion"
        assert [e["id"] for e in definition["conversion"]["events"][0]["filters"]["events"]] == [
            "plan purchased",
            "plan upgraded",
        ]
        trigger = definition["actions"][0]["config"]["filters"]
        assert trigger["properties"] == [{"key": "email", "type": "person", "operator": "is_set", "value": "is_set"}]
        assert [a["type"] for a in definition["actions"]] == [
            "trigger",
            "delay",
            "function_email",
            "delay",
            "function_email",
            "exit",
        ]
        ids = [a["id"] for a in definition["actions"]]
        assert [(e["from"], e["to"]) for e in definition["edges"]] == list(zip(ids, ids[1:]))

    def test_every_email_can_unsubscribe_and_opens_in_the_visual_editor(self):
        for action in _emails(build_idea_definition(_spec())):
            value = action["config"]["inputs"]["email"]["value"]
            assert "{{ unsubscribe_url }}" in value["html"]
            assert "{{ unsubscribe_url }}" in value["text"]
            blocks = value["design"]["body"]["rows"][0]["columns"][0]["contents"]
            assert [b["type"] for b in blocks] == ["heading", "text", "button", "custom"]
            assert "{{ unsubscribe_url }}" in blocks[-1]["values"]["unsubscribe_link_content"]
            assert "&lt;safe&gt;" in value["html"] and "<safe>" not in value["html"]
            assert action["config"]["utm_params"]["utm_campaign"] == "trial-nudge"

    @parameterized.expand(
        [
            ("project site", "https://app.example.com/", "https://app.example.com/pricing"),
            ("no site yet", None, f"{SITE_PLACEHOLDER}/pricing"),
        ]
    )
    def test_buttons_link_to_the_site(self, _name: str, site_url: str | None, expected: str):
        first = _emails(build_idea_definition(_spec(site_url=site_url)))[0]["config"]["inputs"]["email"]["value"]

        assert f'href="{expected}"' in first["html"]
        button = first["design"]["body"]["rows"][0]["columns"][0]["contents"][2]
        assert button["values"]["href"]["values"]["href"] == expected

    def test_each_email_needs_a_wait(self):
        with self.assertRaises(ValueError):
            build_idea_definition(_spec(waits=["1h"]))

    def test_new_idea_carries_what_the_card_shows(self):
        idea = new_idea_from_draft(
            key="trial-nudge",
            title="Nudge trials toward a plan",
            rationale="Few trials pick a plan in week one.",
            value_tier="revenue",
            evidence={"reachable_people": 1000, "baseline_rate": 0.2, "measured_at": "2026-01-05"},
            spec=_spec(),
        )

        assert idea.evidence["emails_per_month"] == 1900
        assert idea.evidence["waits"] == ["1h", "2d"]
        assert idea.evidence["site_url"] == "https://app.example.com"
        assert idea.evidence["trigger_event"] == "trial started"

    def test_site_prefers_an_exact_https_app_url(self):
        assert (
            find_site_url(0, ["http://insecure.example.com", "https://*.example.com", "https://app.example.com/"])
            == "https://app.example.com"
        )
