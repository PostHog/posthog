import pytest

from posthog.models import Organization

from products.posthog_ai.eval_harness.data_setup import _case_org_name, claim_demo_team, create_empty_eval_project
from products.posthog_ai.eval_harness.harness.django_env import NullDbBlocker


def test_case_org_name_fits_the_organization_name_column() -> None:
    name = _case_org_name("governed_metric_proposed_with_approved_sibling", "1a2b3c4d")

    max_length = Organization._meta.get_field("name").max_length
    assert max_length is not None
    assert len(name) <= max_length
    assert name.endswith("-1a2b3c4d)")


@pytest.mark.django_db
def test_claimed_team_is_single_use_and_scoped_to_its_master() -> None:
    blocker = NullDbBlocker()
    master, _ = create_empty_eval_project(blocker, label="master")
    other, _ = create_empty_eval_project(blocker, label="other-master")
    fresh, user = create_empty_eval_project(blocker, label="prewarm")
    master.extra_settings = {"eval_ready_team_ids": [fresh.id], "eval_fixture_clock": "retained"}
    master.save(update_fields=["extra_settings"])

    assert claim_demo_team(other.id, blocker, "unrelated") is None
    assert claim_demo_team(master.id, blocker, "first") == (fresh, user)
    assert claim_demo_team(master.id, blocker, "second") is None
    master.refresh_from_db()
    fresh.organization.refresh_from_db()
    assert fresh.organization.name.startswith("Hedgebox (first-")
    assert master.extra_settings == {"eval_ready_team_ids": [], "eval_fixture_clock": "retained"}
