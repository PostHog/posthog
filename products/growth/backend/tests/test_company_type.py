from django.test import SimpleTestCase

from parameterized import parameterized

from products.growth.backend.enrichment.classifier import CompanyType, classify_company_type


class TestClassifyCompanyType(SimpleTestCase):
    @parameterized.expand(
        [
            ("yc_lowercase", "founder@stripe.com", CompanyType.YC),
            ("yc_posthog", "dev@posthog.com", CompanyType.YC),
            ("yc_mixed_case", "Founder@Stripe.com", CompanyType.YC),
            ("enterprise_microsoft", "cto@microsoft.com", CompanyType.ENTERPRISE),
            ("enterprise_jpmorgan", "person@jpmorgan.com", CompanyType.ENTERPRISE),
            ("personal_gmail", "someone@gmail.com", CompanyType.PERSONAL_EMAIL),
            ("personal_hotmail_mixed_case", "someone@Hotmail.com", CompanyType.PERSONAL_EMAIL),
            ("work_other", "eng@some-startup.io", CompanyType.WORK_EMAIL_OTHER),
            ("empty_string", "", CompanyType.UNKNOWN),
            ("no_at_sign", "not-an-email", CompanyType.UNKNOWN),
            ("trailing_at", "trailing@", CompanyType.UNKNOWN),
        ]
    )
    def test_classify_company_type(self, _name, email, expected):
        assert classify_company_type(email) == expected

    def test_classify_returns_stringifiable_enum(self):
        result = classify_company_type("founder@stripe.com")
        assert isinstance(result, str)
        assert result == "yc"

    def test_yc_takes_precedence_over_generic_check(self):
        assert classify_company_type("x@stripe.com") == CompanyType.YC
