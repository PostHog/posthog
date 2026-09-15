import datetime as dt
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.core.management import CommandError, call_command

from posthog.models.instance_setting import override_instance_config
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.models import EnrichmentSignupSnapshot, OrganizationEnrichment, OrganizationEnrichmentFetch
from products.growth.backend.temporal.signup_enrichment.workflow import SignupEnrichmentInputs

_LOGIC_MODULE = "products.growth.backend.enrichment.signup_backfill"
_GATES_MODULE = "products.growth.backend.enrichment.gates"


def _window() -> dict[str, str]:
    return {
        "after": (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat(),
        "before": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(),
    }


def _stamp(org: Organization) -> str:
    return f"{org.id} ({org.created_at:%Y-%m-%d %H:%M})"


def _inputs(org: Organization) -> SignupEnrichmentInputs:
    user = org.memberships.get().user
    assert user.distinct_id is not None
    return SignupEnrichmentInputs(
        organization_id=str(org.id), distinct_id=user.distinct_id, domain=user.email.rsplit("@", 1)[1]
    )


class _SignupBackfillTestCase(BaseTest):
    def setUp(self):
        super().setUp()
        self.enterContext(override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", True))

    def _org(
        self,
        *,
        email: str,
        work_email: bool = True,
        fetched: bool = False,
        snapshotted: bool = False,
        joined_after: dt.timedelta | None = None,
        created_at: dt.datetime | None = None,
        member: bool = True,
    ) -> Organization:
        org = Organization.objects.create(name=email)
        if created_at is not None:
            Organization.objects.filter(id=org.id).update(created_at=created_at)
            org.created_at = created_at
        if member:
            user = User.objects.create_user(email=email, password=None, first_name="t")
            membership = OrganizationMembership.objects.create(organization=org, user=user)
            OrganizationMembership.objects.filter(id=membership.id).update(
                joined_at=org.created_at + (joined_after or dt.timedelta())
            )
        OrganizationEnrichment.objects.create(organization=org, data={"work_email": work_email})
        if fetched:
            OrganizationEnrichmentFetch.objects.create(organization=org, provider="harmonic", payload={})
        if snapshotted:
            EnrichmentSignupSnapshot.objects.create(organization=org)
        return org


class TestBackfillSignupEnrichment(_SignupBackfillTestCase):
    def test_dispatches_only_eligible_orgs_without_a_fetch(self):
        target = self._org(email="a@stripe.com")
        self._org(email="b@vercel.com", fetched=True)
        self._org(email="c@gmail.com", work_email=False)
        self._org(email="d@sentry.io", snapshotted=True)
        self._org(email="e@linear.app", joined_after=dt.timedelta(days=2))

        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.dispatch_signup_enrichment") as dispatch,
        ):
            call_command("backfill_signup_enrichment", "--delay=0", **_window())

        assert dispatch.call_count == 1
        inputs = dispatch.call_args.args[0]
        assert inputs.organization_id == str(target.id)
        assert inputs.domain == "stripe.com"
        assert inputs.distinct_id == target.memberships.get().user.distinct_id

    def test_refuses_when_kill_switch_off(self):
        with override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", False):
            with self.assertRaises(CommandError):
                call_command("backfill_signup_enrichment", **_window())

    def test_dispatches_in_eu(self):
        target = self._org(email="a@stripe.com")

        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="EU"),
            patch(f"{_LOGIC_MODULE}.dispatch_signup_enrichment") as dispatch,
        ):
            call_command("backfill_signup_enrichment", "--delay=0", **_window())

        assert dispatch.call_count == 1
        assert dispatch.call_args.args[0].organization_id == str(target.id)

    def test_refuses_outside_us_and_eu(self):
        self._org(email="a@stripe.com")
        with patch(f"{_GATES_MODULE}.get_instance_region", return_value="DEV"):
            with self.assertRaises(CommandError):
                call_command("backfill_signup_enrichment", **_window())

    def test_continues_past_a_failed_dispatch(self):
        self._org(email="a@stripe.com")
        second = self._org(email="b@vercel.com")

        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(
                f"{_LOGIC_MODULE}.dispatch_signup_enrichment", side_effect=[RuntimeError("temporal down"), None]
            ) as dispatch,
        ):
            call_command("backfill_signup_enrichment", "--delay=0", **_window())

        assert dispatch.call_count == 2
        assert dispatch.call_args.args[0].organization_id == str(second.id)

    def test_dry_run_dispatches_nothing(self):
        self._org(email="a@stripe.com")
        with (
            patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"),
            patch(f"{_LOGIC_MODULE}.dispatch_signup_enrichment") as dispatch,
        ):
            call_command("backfill_signup_enrichment", "--dry-run", **_window())

        dispatch.assert_not_called()


class TestBackfillSignupEnrichmentGolden(_SignupBackfillTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch(f"{_GATES_MODULE}.get_instance_region", return_value="US"))
        self.dispatch = self.enterContext(patch(f"{_LOGIC_MODULE}.dispatch_signup_enrichment"))
        self.out = StringIO()
        self.err = StringIO()
        self.now = dt.datetime.now(dt.UTC)

    def _run(self, *args: str, **options: Any) -> tuple[str, str]:
        call_command(
            "backfill_signup_enrichment",
            "--delay=0",
            *args,
            stdout=self.out,
            stderr=self.err,
            no_color=True,
            **{**_window(), **options},
        )
        return self.out.getvalue(), self.err.getvalue()

    def _minutes_ago(self, minutes: int) -> dt.datetime:
        return self.now - dt.timedelta(minutes=minutes)

    def test_dispatches_eligible_orgs_by_created_at_and_prints_a_skip_line_per_skip_reason(self):
        left = self._org(email="b@vercel.com", joined_after=dt.timedelta(days=2), created_at=self._minutes_ago(20))
        memberless = self._org(email="c@linear.app", member=False, created_at=self._minutes_ago(10))
        eligible = self._org(email="a@stripe.com", created_at=self._minutes_ago(30))
        self._org(email="d@sentry.io", fetched=True, created_at=self._minutes_ago(40))
        self._org(email="e@notion.so", snapshotted=True, created_at=self._minutes_ago(50))

        stdout, stderr = self._run()

        assert stdout == (
            f"dispatched {_stamp(eligible)} domain=stripe.com\n"
            f"skip {_stamp(left)} (signup user no longer a member)\n"
            f"skip {_stamp(memberless)} (no usable signup member)\n"
            "dispatched 1, skipped 2, errored 0\n"
        )
        assert stderr == ""
        assert self.dispatch.call_args_list == [call(_inputs(eligible))]
        assert not OrganizationEnrichmentFetch.objects.filter(organization=eligible).exists()

    def test_a_failed_dispatch_is_reported_on_stderr_and_the_run_continues(self):
        failed = self._org(email="a@stripe.com", created_at=self._minutes_ago(30))
        dispatched = self._org(email="b@vercel.com", created_at=self._minutes_ago(20))
        self.dispatch.side_effect = [RuntimeError("temporal down"), None]

        stdout, stderr = self._run()

        assert stdout == f"dispatched {_stamp(dispatched)} domain=vercel.com\ndispatched 1, skipped 0, errored 1\n"
        assert stderr == (
            f"error {_stamp(failed)}: temporal down\n"
            "re-run the same window to retry errored orgs; completed orgs are excluded\n"
        )
        assert self.dispatch.call_args_list == [call(_inputs(failed)), call(_inputs(dispatched))]

    def test_dry_run_lists_without_dispatching(self):
        eligible = self._org(email="a@stripe.com", created_at=self._minutes_ago(30))
        left = self._org(email="b@vercel.com", joined_after=dt.timedelta(days=2), created_at=self._minutes_ago(20))

        stdout, stderr = self._run("--dry-run")

        assert stdout == (
            f"would dispatch {_stamp(eligible)} domain=stripe.com\n"
            f"skip {_stamp(left)} (signup user no longer a member)\n"
            "would dispatch 1, skipped 1, errored 0\n"
        )
        assert stderr == ""
        self.dispatch.assert_not_called()

    def test_limit_counts_dispatches_only(self):
        left = self._org(email="a@vercel.com", joined_after=dt.timedelta(days=2), created_at=self._minutes_ago(30))
        first = self._org(email="b@stripe.com", created_at=self._minutes_ago(20))
        self._org(email="c@linear.app", created_at=self._minutes_ago(10))

        stdout, stderr = self._run(limit=1)

        assert stdout == (
            f"skip {_stamp(left)} (signup user no longer a member)\n"
            f"dispatched {_stamp(first)} domain=stripe.com\n"
            "dispatched 1, skipped 1, errored 0\n"
        )
        assert stderr == ""
        assert self.dispatch.call_args_list == [call(_inputs(first))]

    def test_refuses_with_an_exact_message_before_touching_any_org(self):
        self._org(email="a@stripe.com")
        window = _window()

        with override_instance_config("GROWTH_SIGNUP_ENRICHMENT_ENABLED", False):
            with self.assertRaises(CommandError) as disabled:
                self._run()
        assert (
            str(disabled.exception)
            == "Signup enrichment is disabled (GROWTH_SIGNUP_ENRICHMENT_ENABLED); refusing to dispatch"
        )

        with patch(f"{_GATES_MODULE}.get_instance_region", return_value="DEV"):
            with self.assertRaises(CommandError) as region:
                self._run()
        assert str(region.exception) == "Signup enrichment is US/EU-only; refusing to dispatch in this region"

        with self.assertRaises(CommandError) as inverted:
            self._run(after=window["before"], before=window["after"])
        assert str(inverted.exception) == "--after must be earlier than --before"

        with self.assertRaises(CommandError) as unparseable:
            self._run(after="yesterday")
        assert str(unparseable.exception) == "Invalid ISO 8601 datetime: 'yesterday'"

        assert self.out.getvalue() == ""
        assert self.err.getvalue() == ""
        self.dispatch.assert_not_called()
