from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.workflows.backend.services.existing_email_tools import (
    detect_existing_email_tools,
    lookup_existing_email_tools,
)


class TestDetectExistingEmailTools(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "spf_includes",
                ["v=spf1 include:servers.mcsv.net include:sendgrid.net ~all"],
                [],
                False,
                ["Mailchimp", "SendGrid"],
            ),
            ("not_spf", ["google-site-verification=include:sendgrid.net"], [], False, []),
            ("dkim_cname", [], ["s1.domainkey.u123.wl.sendgrid.net."], False, ["SendGrid"]),
            ("resend_dkim", [], [], True, ["Resend"]),
            (
                "deduplicated",
                ["v=spf1 include:spf.brevo.com ~all"],
                ["b1.example-com.dkim.brevo.com."],
                False,
                ["Brevo"],
            ),
        ]
    )
    def test_names_tools_from_dns(
        self, _name: str, spf_records: list[str], dkim_targets: list[str], has_resend_dkim: bool, expected: list[str]
    ) -> None:
        assert (
            detect_existing_email_tools(
                spf_records=spf_records, dkim_targets=dkim_targets, has_resend_dkim=has_resend_dkim
            )
            == expected
        )


class TestOOBDomainGuard(SimpleTestCase):
    # A host per case, because the lookup caches its answer per domain.
    @parameterized.expand([("on_cloud", True, "cloud.oast.live"), ("off_cloud", False, "selfhosted.oast.live")])
    def test_a_listed_domain_is_refused_on_cloud_only(self, _name: str, cloud: bool, domain: str) -> None:
        module = "products.workflows.backend.services.existing_email_tools"
        with (
            patch(f"{module}.is_cloud", return_value=cloud),
            patch(f"{module}._resolve", return_value=None) as resolve,
        ):
            assert lookup_existing_email_tools(domain) == []

        assert resolve.called is not cloud
