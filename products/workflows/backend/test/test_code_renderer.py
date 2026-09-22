import json
from dataclasses import asdict
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.services.code_renderer import render_workflow_code

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "code_renderer"

# The warnings each fixture must report, in order. A fixture absent here renders with none.
EXPECTED_WARNINGS: dict[str, list[dict[str, str | None]]] = {
    "crm_follow_up": [
        {
            "action_id": "tell_the_crm",
            "message": 'The input "signing_secret" of "Tell the CRM" is a secret. PostHog does not return its value, so set TELL_THE_CRM_SIGNING_SECRET before you push.',
        },
    ],
    "re_engagement": [
        {
            "action_id": "wait_for_a_click",
            "message": 'The branch edges out of "Wait for a click" are dropped. Only its next step is kept.',
        },
        {
            "action_id": "wait_for_a_click",
            "message": 'The wait_until_condition step "Wait for a click" has no constructor in @posthog/workflows. It is kept in place as a comment.',
        },
        {
            "action_id": "text_them",
            "message": 'The function_sms step "Text them" has no constructor in @posthog/workflows. It is kept in place as a comment.',
        },
        {
            "action_id": "nudge_by_email",
            "message": 'The email design of "Nudge by email" was edited in the visual editor. @posthog/workflows rebuilds the design from html, so that layout is dropped.',
        },
    ],
    "trial_nudge": [
        {
            "action_id": "trigger_node",
            "message": "The trigger filters out test accounts. @posthog/workflows cannot set that, so a push turns it off.",
        },
        {
            "action_id": "exit_node",
            "message": 'The exit condition "exit_on_conversion" needs a conversion goal, which @posthog/workflows cannot declare. The workflow exits only at the end.',
        },
    ],
}


def _cases() -> list[str]:
    return sorted(path.stem for path in FIXTURES.glob("*.json") if not path.name.endswith(".roundtrip.json"))


class TestCodeRenderer(SimpleTestCase):
    @parameterized.expand(_cases())
    def test_renders_fixture_byte_for_byte(self, case: str) -> None:
        definition = json.loads((FIXTURES / f"{case}.json").read_text())

        rendered = render_workflow_code(definition)

        assert rendered.code == (FIXTURES / f"{case}.ts").read_text()
        assert [asdict(warning) for warning in rendered.warnings] == EXPECTED_WARNINGS.get(case, [])
