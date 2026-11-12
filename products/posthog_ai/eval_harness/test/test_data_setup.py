from posthog.models import Organization

from products.posthog_ai.eval_harness.data_setup import _case_org_name


def test_case_org_name_fits_the_organization_name_column() -> None:
    name = _case_org_name("governed_metric_proposed_with_approved_sibling", "1a2b3c4d")

    max_length = Organization._meta.get_field("name").max_length
    assert max_length is not None
    assert len(name) <= max_length
    assert name.endswith("-1a2b3c4d)")
