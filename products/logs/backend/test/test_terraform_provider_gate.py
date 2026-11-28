from django.test import SimpleTestCase

from parameterized import parameterized

from products.logs.backend.presentation.views.terraform_provider_gate import (
    TerraformProviderUpgradeRequired,
    refuse_untrackable_terraform_create,
)


class TestRefuseUntrackableTerraformCreate(SimpleTestCase):
    @parameterized.expand(
        [
            ("released_before_row_ids", "1.0.31"),
            ("local_build_of_an_old_tag", "v1.0.27-26.gabc1234"),
            ("dirty_local_build", "v1.0.26-dirty"),
            ("build_with_no_tag_in_reach", "v0.0.0-1-gabc1234-dirty"),
        ]
    )
    def test_refuses_a_provider_that_tracks_destinations_by_hog_function_ids(self, _name: str, version: str) -> None:
        with self.assertRaises(TerraformProviderUpgradeRequired) as raised:
            refuse_untrackable_terraform_create(f"posthog/terraform-provider; version: {version}")

        assert raised.exception.status_code == 400
        assert raised.exception.default_code == "terraform_provider_upgrade_required"
        assert f"PostHog Terraform provider {version} can't track them" in str(raised.exception.detail)
        assert "Upgrade the provider to 1.0.32 or later" in str(raised.exception.detail)

    @parameterized.expand(
        [
            ("first_row_id_release", "posthog/terraform-provider; version: 1.0.32"),
            ("later_minor_release", "posthog/terraform-provider; version: v1.1.0"),
            ("build_from_a_checkout", "posthog/terraform-provider; version: dev"),
            ("provider_acceptance_tests", "posthog/terraform-provider; version: acceptance-test"),
            ("not_terraform", "python-requests/2.32.3"),
            ("no_user_agent", ""),
        ]
    )
    def test_lets_other_callers_through(self, _name: str, user_agent: str) -> None:
        refuse_untrackable_terraform_create(user_agent)
