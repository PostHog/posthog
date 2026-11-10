from unittest.mock import patch

from django.test import SimpleTestCase

from posthog.models import Team, User

from products.ui_customization.backend.facade.feature_flags import is_enabled_for


class TestUICustomizationFlag(SimpleTestCase):
    def test_only_the_customization_flag_controls_access(self) -> None:
        user = User(distinct_id="synthetic-user", email="person@example.com")
        team = Team(id=123, organization_id="00000000-0000-0000-0000-000000000001")
        with patch("posthog.permissions.posthoganalytics.feature_enabled", return_value=True) as flag:
            assert is_enabled_for(user, team) is True
        assert flag.call_args.args == ("ui-customization", "synthetic-user")
        assert flag.call_args.kwargs["groups"]["project"] == "123"

    def test_flag_service_failure_denies_access(self) -> None:
        with patch(
            "posthog.permissions.posthoganalytics.feature_enabled",
            side_effect=RuntimeError("unavailable"),
        ):
            assert is_enabled_for(User(distinct_id="synthetic-user"), Team(id=123)) is False
