import pytest

from products.growth.backend.enrichment.classifier import CompanyType, classify_company_type


@pytest.mark.parametrize(
    "email,expected",
    [
        ("founder@stripe.com", CompanyType.YC),
        ("dev@posthog.com", CompanyType.YC),
        ("Founder@Stripe.com", CompanyType.YC),
        ("cto@microsoft.com", CompanyType.ENTERPRISE),
        ("person@jpmorgan.com", CompanyType.ENTERPRISE),
        ("someone@gmail.com", CompanyType.PERSONAL_EMAIL),
        ("someone@Hotmail.com", CompanyType.PERSONAL_EMAIL),
        ("eng@some-startup.io", CompanyType.WORK_EMAIL_OTHER),
        ("", CompanyType.UNKNOWN),
        ("not-an-email", CompanyType.UNKNOWN),
        ("trailing@", CompanyType.UNKNOWN),
    ],
)
def test_classify_company_type(email, expected):
    assert classify_company_type(email) == expected


def test_classify_returns_stringifiable_enum():
    result = classify_company_type("founder@stripe.com")
    assert isinstance(result, str)
    assert result == "yc"


def test_yc_takes_precedence_over_generic_check():
    assert classify_company_type("x@stripe.com") == CompanyType.YC
