from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.facade.contracts import TeamUtmDefaults
from products.workflows.backend.services.email_utm_defaults import (
    UTM_FROM_DEFAULT_KEY,
    UTM_KEYS,
    release_edited_keys,
    seed_new_email_actions,
)

DEFAULTS = TeamUtmDefaults(
    enabled=True, params={"utm_source": "newsletter", "utm_campaign": "{{ person.properties.plan }}"}
)


def _email(action_id: str, **config: Any) -> dict[str, Any]:
    return {"id": action_id, "type": "function_email", "config": {"template_id": "template-email", **config}}


class TestEmailUtmDefaults(SimpleTestCase):
    def test_seed_new_email_actions_only_fills_new_steps_without_a_choice(self) -> None:
        actions = [
            _email("existing"),
            _email("new_unset"),
            _email("new_chosen", utm_tags_enabled=False),
            _email("new_with_values", utm_params={"utm_source": "partner"}),
            _email("new_chosen_with_values", utm_tags_enabled=True, utm_params={"utm_source": "partner"}),
            _email("new_with_marker", **{UTM_FROM_DEFAULT_KEY: ["utm_medium"]}),
            _email("new_with_empty_campaign", utm_params={"utm_campaign": ""}),
            {"id": "trigger", "type": "trigger", "config": {}},
        ]

        seed_new_email_actions(actions, ["existing"], DEFAULTS)

        configs = {action["id"]: action["config"] for action in actions}
        assert "utm_tags_enabled" not in configs["existing"]
        assert configs["new_unset"]["utm_tags_enabled"] is True
        assert configs["new_unset"]["utm_params"] == DEFAULTS.params
        assert configs["new_unset"][UTM_FROM_DEFAULT_KEY] == list(UTM_KEYS)
        assert configs["new_chosen"] == {
            "template_id": "template-email",
            "utm_tags_enabled": False,
            UTM_FROM_DEFAULT_KEY: list(UTM_KEYS),
        }
        assert configs["new_chosen_with_values"]["utm_params"] == {"utm_source": "partner"}
        assert configs["new_chosen_with_values"][UTM_FROM_DEFAULT_KEY] == ["utm_medium", "utm_campaign", "utm_content"]
        assert configs["new_with_marker"][UTM_FROM_DEFAULT_KEY] == ["utm_medium"]
        assert configs["new_with_values"]["utm_params"] == {
            "utm_source": "partner",
            "utm_campaign": "{{ person.properties.plan }}",
        }
        assert configs["new_with_values"][UTM_FROM_DEFAULT_KEY] == ["utm_medium", "utm_campaign", "utm_content"]
        assert configs["new_with_empty_campaign"]["utm_params"] == {"utm_source": "newsletter", "utm_campaign": ""}
        assert configs["new_with_empty_campaign"][UTM_FROM_DEFAULT_KEY] == ["utm_source", "utm_medium", "utm_content"]

    @parameterized.expand(
        [
            (
                "an edited value stops following the default",
                {"utm_params": {"utm_source": "newsletter"}},
                None,
                {"utm_params": {"utm_source": "partner"}, UTM_FROM_DEFAULT_KEY: list(UTM_KEYS)},
                False,
                ["utm_medium", "utm_campaign", "utm_content"],
            ),
            (
                "a step only the staged draft has is compared with the draft",
                None,
                {"utm_params": {"utm_source": "newsletter"}},
                {"utm_params": {"utm_source": "partner"}, UTM_FROM_DEFAULT_KEY: list(UTM_KEYS)},
                True,
                ["utm_medium", "utm_campaign", "utm_content"],
            ),
            (
                "a value changed to the team default keeps following it",
                {"utm_params": {"utm_source": "partner"}},
                None,
                {"utm_params": {"utm_source": "newsletter"}, UTM_FROM_DEFAULT_KEY: list(UTM_KEYS)},
                False,
                list(UTM_KEYS),
            ),
            (
                "an unchanged step from before team defaults gets no marker",
                {"utm_params": {"utm_source": "old"}},
                None,
                {"utm_params": {"utm_source": "old"}},
                False,
                None,
            ),
            (
                "a resend without the marker keeps the stored marker",
                {"utm_params": {"utm_source": "partner"}, UTM_FROM_DEFAULT_KEY: ["utm_medium"]},
                None,
                {"utm_params": {"utm_source": "partner"}},
                False,
                ["utm_medium"],
            ),
            (
                "an unchanged draft value is compared with the draft, not the live step",
                {"utm_params": {"utm_source": "spring"}},
                {"utm_params": {"utm_source": "summer"}},
                {"utm_params": {"utm_source": "summer"}, UTM_FROM_DEFAULT_KEY: list(UTM_KEYS)},
                True,
                list(UTM_KEYS),
            ),
        ]
    )
    def test_release_edited_keys(
        self,
        _name: str,
        live_config: dict[str, Any] | None,
        draft_config: dict[str, Any] | None,
        submitted_config: dict[str, Any],
        saving_draft: bool,
        expected_marker: list[str] | None,
    ) -> None:
        stored_actions = [_email("email_1", **live_config)] if live_config is not None else []
        stored_draft = {"actions": [_email("email_1", **draft_config)]} if draft_config is not None else None
        actions = [_email("email_1", **submitted_config)]

        release_edited_keys(actions, stored_actions, stored_draft, DEFAULTS, saving_draft=saving_draft)

        assert actions[0]["config"].get(UTM_FROM_DEFAULT_KEY) == expected_marker
