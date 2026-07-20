import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.models import EnrichmentSignupSnapshot, OrganizationEnrichment, OrganizationEnrichmentFetch

_COMMAND_MODULE = "products.growth.backend.management.commands.backfill_signup_enrichment"


def _window() -> dict[str, str]:
    return {
        "after": (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat(),
        "before": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(),
    }


class TestBackfillSignupEnrichment(BaseTest):
    def _org(
        self,
        *,
        email: str,
        work_email: bool = True,
        fetched: bool = False,
        snapshotted: bool = False,
        joined_after: dt.timedelta | None = None,
    ) -> Organization:
        org = Organization.objects.create(name=email)
        user = User.objects.create_user(email=email, password=None, first_name="t")
        membership = OrganizationMembership.objects.create(organization=org, user=user)
        if joined_after is not None:
            OrganizationMembership.objects.filter(id=membership.id).update(joined_at=org.created_at + joined_after)
        OrganizationEnrichment.objects.create(organization=org, data={"work_email": work_email})
        if fetched:
            OrganizationEnrichmentFetch.objects.create(organization=org, provider="harmonic", payload={})
        if snapshotted:
            EnrichmentSignupSnapshot.objects.create(organization=org)
        return org

    def test_dispatches_only_eligible_orgs_without_a_fetch(self):
        target = self._org(email="a@stripe.com")
        self._org(email="b@vercel.com", fetched=True)
        self._org(email="c@gmail.com", work_email=False)
        self._org(email="d@sentry.io", snapshotted=True)
        self._org(email="e@linear.app", joined_after=dt.timedelta(days=2))

        with (
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.dispatch_signup_enrichment") as dispatch,
        ):
            call_command("backfill_signup_enrichment", "--delay=0", **_window())

        assert dispatch.call_count == 1
        inputs = dispatch.call_args.args[0]
        assert inputs.organization_id == str(target.id)
        assert inputs.domain == "stripe.com"
        assert inputs.distinct_id == target.memberships.get().user.distinct_id

    def test_dry_run_dispatches_nothing(self):
        self._org(email="a@stripe.com")
        with (
            patch(f"{_COMMAND_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_COMMAND_MODULE}.dispatch_signup_enrichment") as dispatch,
        ):
            call_command("backfill_signup_enrichment", "--dry-run", **_window())

        dispatch.assert_not_called()
