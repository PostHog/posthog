from typing import Literal

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from products.ui_customization.backend.facade.fragments import (
    FragmentLayout,
    FragmentLink,
    FragmentModel,
    FragmentSection,
)


class SettingsTarget(FragmentModel):
    kind: Literal["settings"]


SettingsFragment = FragmentLayout[FragmentSection[FragmentLink[SettingsTarget]]]


class TestFragmentShapes(SimpleTestCase):
    @parameterized.expand([("settings", True), ("page", False)])
    def test_targets_come_from_the_context_schema(self, kind: str, accepted: bool) -> None:
        content = {"sections": [{"id": "settings", "items": [{"type": "link", "to": {"kind": kind}}]}]}
        if accepted:
            fragment = SettingsFragment.model_validate(content)
            self.assertEqual(fragment.model_dump(exclude_none=True), {"version": 1, **content})
        else:
            with self.assertRaises(ValidationError):
                SettingsFragment.model_validate(content)
