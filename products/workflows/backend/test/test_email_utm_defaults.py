from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.facade.contracts import TeamUtmDefaults
from products.workflows.backend.services.email_utm_defaults import (
    UTM_FROM_DEFAULT_KEY,
    UTM_KEYS,
    apply_defaults_to_email_config,
    release_edited_keys,
    seed_new_email_actions,
)

DEFAULTS = TeamUtmDefaults(
    enabled=True, params={"utm_source": "newsletter", "utm_campaign": "{{ person.properties.plan }}"}
)


def _email(action_id: str, **config: Any) -> dict[str, Any]:
    return {"id": action_id, "type": "function_email", "config": {"template_id": "template-email", **config}}


class TestEmailUtmDefaults(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "a step from before team defaults follows every default",
                {"utm_tags_enabled": True, "utm_params": {"utm_source": "old"}},
                False,
                {"utm_source": "newsletter", "utm_campaign": "{{ person.properties.plan }}"},
                True,
            ),
            (
                "a value typed into the email survives",
                {
                    "utm_tags_enabled": True,
                    "utm_params": {"utm_source": "partner"},
                    UTM_FROM_DEFAULT_KEY: ["utm_medium", "utm_campaign", "utm_content"],
                },
                False,
                {"utm_source": "partner", "utm_campaign": "{{ person.properties.plan }}"},
                True,
            ),
            (
                "tags stay off unless asked to turn them on",
                {"utm_tags_enabled": False},
                False,
                {"utm_source": "newsletter", "utm_campaign": "{{ person.properties.plan }}"},
                False,
            ),
            (
                "tags turn on when asked",
                {},
                True,
                {"utm_source": "newsletter", "utm_campaign": "{{ person.properties.plan }}"},
                True,
            ),
        ]
    )
    def test_apply_defaults_to_email_config(
        self, _name: str, config: dict[str, Any], enable_where_off: bool, expected_params: dict, expected_on: bool
    ) -> None:
        updated = apply_defaults_to_email_config(config, DEFAULTS, enable_where_off)

        assert updated is not None
        assert updated["utm_params"] == expected_params
        assert (updated.get("utm_tags_enabled") is True) == expected_on

    def test_apply_defaults_to_email_config_returns_none_when_nothing_changes(self) -> None:
        config = {
            "utm_tags_enabled": True,
            "utm_params": {"utm_source": "newsletter", "utm_campaign": "{{ person.properties.plan }}"},
            UTM_FROM_DEFAULT_KEY: list(UTM_KEYS),
        }

        assert apply_defaults_to_email_config(config, DEFAULTS, enable_where_off=True) is None

    def test_seed_new_email_actions_only_fills_new_steps_without_a_choice(self) -> None:
        actions = [
            _email("existing"),
            _email("new_unset"),
            _email("new_chosen", utm_tags_enabled=False),
            _email("new_with_values", utm_params={"utm_source": "partner"}),
            {"id": "trigger", "type": "trigger", "config": {}},
        ]

        seed_new_email_actions(actions, ["existing"], DEFAULTS)

        configs = {action["id"]: action["config"] for action in actions}
        assert "utm_tags_enabled" not in configs["existing"]
        assert configs["new_unset"]["utm_tags_enabled"] is True
        assert configs["new_unset"]["utm_params"] == DEFAULTS.params
        assert configs["new_unset"][UTM_FROM_DEFAULT_KEY] == list(UTM_KEYS)
        assert configs["new_chosen"] == {"template_id": "template-email", "utm_tags_enabled": False}
        assert configs["new_with_values"]["utm_params"] == {
            "utm_source": "partner",
            "utm_campaign": "{{ person.properties.plan }}",
        }
        assert configs["new_with_values"][UTM_FROM_DEFAULT_KEY] == ["utm_medium", "utm_campaign", "utm_content"]

    @parameterized.expand(
        [
            (
                "an edited value stops following the default",
                {"utm_source": "newsletter"},
                None,
                {"utm_params": {"utm_source": "partner"}, UTM_FROM_DEFAULT_KEY: list(UTM_KEYS)},
                ["utm_medium", "utm_campaign", "utm_content"],
            ),
            (
                "a step only the staged draft has is compared with the draft",
                None,
                {"utm_source": "newsletter"},
                {"utm_params": {"utm_source": "partner"}, UTM_FROM_DEFAULT_KEY: list(UTM_KEYS)},
                ["utm_medium", "utm_campaign", "utm_content"],
            ),
            (
                "a value changed to the team default keeps following it",
                {"utm_source": "partner"},
                None,
                {"utm_params": {"utm_source": "newsletter"}, UTM_FROM_DEFAULT_KEY: list(UTM_KEYS)},
                list(UTM_KEYS),
            ),
            (
                "an unchanged step from before team defaults gets no marker",
                {"utm_source": "old"},
                None,
                {"utm_params": {"utm_source": "old"}},
                None,
            ),
        ]
    )
    def test_release_edited_keys(
        self,
        _name: str,
        live_params: dict[str, str] | None,
        draft_params: dict[str, str] | None,
        submitted_config: dict[str, Any],
        expected_marker: list[str] | None,
    ) -> None:
        stored_actions = [_email("email_1", utm_params=live_params)] if live_params is not None else []
        stored_draft = {"actions": [_email("email_1", utm_params=draft_params)]} if draft_params is not None else None
        actions = [_email("email_1", **submitted_config)]

        release_edited_keys(actions, stored_actions, stored_draft, DEFAULTS)

        assert actions[0]["config"].get(UTM_FROM_DEFAULT_KEY) == expected_marker
