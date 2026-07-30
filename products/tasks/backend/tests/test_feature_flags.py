import pytest
from unittest.mock import patch

from django.test import override_settings

from products.tasks.backend.feature_flags import is_dev_stack_image_bake_enabled


class TestIsDevStackImageBakeEnabled:
    @pytest.mark.parametrize("flag_value, expected", [(True, True), (False, False), (None, False)])
    def test_reflects_flag_and_scopes_by_region(self, flag_value, expected):
        with (
            override_settings(DEBUG=False),
            patch("products.tasks.backend.feature_flags.get_instance_region", return_value="US"),
            patch(
                "products.tasks.backend.feature_flags.posthoganalytics.feature_enabled",
                return_value=flag_value,
            ) as feature_enabled_mock,
        ):
            assert is_dev_stack_image_bake_enabled() is expected

        # The region person property is the flag's release-condition input: dropping it
        # would make a region-scoped condition never match and silently stop all bakes.
        assert feature_enabled_mock.call_args.kwargs["person_properties"] == {"region": "US"}

    def test_fails_closed_on_flag_service_error(self):
        # A flag-service outage must not start a paid Modal bake.
        with (
            override_settings(DEBUG=False),
            patch(
                "products.tasks.backend.feature_flags.posthoganalytics.feature_enabled",
                side_effect=RuntimeError("flag service failed"),
            ),
        ):
            assert is_dev_stack_image_bake_enabled() is False

    def test_debug_short_circuits_false_without_consulting_the_flag(self):
        # Self-capture re-enables posthoganalytics in local dev, so the DEBUG guard is
        # the only thing keeping a locally seeded flag from starting paid Modal bakes.
        with (
            override_settings(DEBUG=True),
            patch(
                "products.tasks.backend.feature_flags.posthoganalytics.feature_enabled",
                return_value=True,
            ) as feature_enabled_mock,
        ):
            assert is_dev_stack_image_bake_enabled() is False

        feature_enabled_mock.assert_not_called()
