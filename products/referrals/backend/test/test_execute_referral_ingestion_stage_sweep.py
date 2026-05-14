"""Tests for the social referral ingestion sweep (`Team.ingested_event` → referee_state)."""

from __future__ import annotations

from posthog.test.base import PostHogTestCase

from posthog.models import Organization, Team

from products.referrals.backend.models import (
    REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY,
    REFEREE_STATE_ERRORS_KEY,
    SocialReferral,
)
from products.referrals.backend.temporal.activities import (
    build_pending_ingestion_snapshot,
    execute_referral_ingestion_stage_sweep,
    process_single_social_referral_ingestion_sync,
    record_ingestion_check_failure_on_referral_sync,
)


class TestExecuteReferralIngestionStageSweep(PostHogTestCase):
    def test_no_flip_when_referee_team_never_ingested(self) -> None:
        referee_org = Organization.objects.create(name="Referee no ingestion")
        Team.objects.create(organization=referee_org, name="T1", ingested_event=False)

        referral = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={str(referee_org.id): {"first_event_sent": False}},
        )

        summary = execute_referral_ingestion_stage_sweep()

        referral.refresh_from_db()
        self.assertEqual(
            referral.referee_state[str(referee_org.id)]["first_event_sent"],
            False,
        )
        self.assertEqual(summary["referees_rows_updated"], 0)

    def test_flips_when_single_referee_org_has_ingested_event(self) -> None:
        referee_org = Organization.objects.create(name="Referee ingested")
        Team.objects.create(organization=referee_org, name="T1", ingested_event=True)

        referral = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={str(referee_org.id): {"first_event_sent": False}},
        )

        summary = execute_referral_ingestion_stage_sweep()

        referral.refresh_from_db()
        self.assertEqual(
            referral.referee_state[str(referee_org.id)]["first_event_sent"],
            True,
        )
        self.assertGreaterEqual(summary["referees_rows_updated"], 1)

    def test_same_row_only_matching_org_flips_when_other_referee_not_ingested(self) -> None:
        org_a = Organization.objects.create(name="Referee A partial")
        org_b = Organization.objects.create(name="Referee B partial")
        Team.objects.create(organization=org_a, name="TA", ingested_event=False)
        Team.objects.create(organization=org_b, name="TB", ingested_event=True)

        referral = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={
                str(org_a.id): {"first_event_sent": False},
                str(org_b.id): {"first_event_sent": False},
            },
        )

        execute_referral_ingestion_stage_sweep()

        referral.refresh_from_db()
        state = referral.referee_state
        self.assertIsInstance(state, dict)
        self.assertEqual(state[str(org_a.id)]["first_event_sent"], False)
        self.assertEqual(state[str(org_b.id)]["first_event_sent"], True)

    def test_same_row_both_referee_orgs_flip_when_both_ingested(self) -> None:
        org_a = Organization.objects.create(name="Referee A both")
        org_b = Organization.objects.create(name="Referee B both")
        Team.objects.create(organization=org_a, name="TA2", ingested_event=True)
        Team.objects.create(organization=org_b, name="TB2", ingested_event=True)

        referral = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={
                str(org_a.id): {"first_event_sent": False},
                str(org_b.id): {"first_event_sent": False},
            },
        )

        summary = execute_referral_ingestion_stage_sweep()

        referral.refresh_from_db()
        state = referral.referee_state
        self.assertIsInstance(state, dict)
        self.assertEqual(state[str(org_a.id)]["first_event_sent"], True)
        self.assertEqual(state[str(org_b.id)]["first_event_sent"], True)
        self.assertEqual(summary["referees_rows_updated"], 2)

    def test_same_referring_org_single_row_multiple_referee_orgs_all_pending_then_one_ingests(
        self,
    ) -> None:
        """One referring org, one SocialReferral, several invited orgs still waiting on first_event_sent."""
        org_a = Organization.objects.create(name="Ref triple A")
        org_b = Organization.objects.create(name="Ref triple B")
        org_c = Organization.objects.create(name="Ref triple C")
        Team.objects.create(organization=org_a, name="TA3", ingested_event=False)
        tb = Team.objects.create(organization=org_b, name="TB3", ingested_event=False)
        Team.objects.create(organization=org_c, name="TC3", ingested_event=False)

        referral = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={
                str(org_a.id): {"first_event_sent": False},
                str(org_b.id): {"first_event_sent": False},
                str(org_c.id): {"first_event_sent": False},
            },
        )

        summary_none = execute_referral_ingestion_stage_sweep()
        self.assertEqual(summary_none["referees_rows_updated"], 0)
        referral.refresh_from_db()
        state0 = referral.referee_state
        self.assertIsInstance(state0, dict)
        for o in (org_a, org_b, org_c):
            self.assertEqual(state0[str(o.id)]["first_event_sent"], False)

        tb.ingested_event = True
        tb.save(update_fields=["ingested_event"])

        summary_one = execute_referral_ingestion_stage_sweep()
        self.assertEqual(summary_one["referees_rows_updated"], 1)
        referral.refresh_from_db()
        state1 = referral.referee_state
        self.assertIsInstance(state1, dict)
        self.assertEqual(state1[str(org_a.id)]["first_event_sent"], False)
        self.assertEqual(state1[str(org_b.id)]["first_event_sent"], True)
        self.assertEqual(state1[str(org_c.id)]["first_event_sent"], False)

    def test_same_referring_org_multiple_social_referral_rows_independent_referee_orgs(
        self,
    ) -> None:
        """Same referring Organization on several SocialReferral rows; each row tracks its own invited orgs."""
        org_a = Organization.objects.create(name="Ref row alpha")
        org_b = Organization.objects.create(name="Ref row beta")
        Team.objects.create(organization=org_a, name="T1m", ingested_event=False)
        Team.objects.create(organization=org_b, name="T2m", ingested_event=False)

        row_alpha = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={str(org_a.id): {"first_event_sent": False}},
        )
        row_beta = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={str(org_b.id): {"first_event_sent": False}},
        )

        execute_referral_ingestion_stage_sweep()
        row_alpha.refresh_from_db()
        row_beta.refresh_from_db()
        self.assertEqual(row_alpha.referee_state[str(org_a.id)]["first_event_sent"], False)
        self.assertEqual(row_beta.referee_state[str(org_b.id)]["first_event_sent"], False)

        Team.objects.filter(organization=org_a).update(ingested_event=True)

        execute_referral_ingestion_stage_sweep()
        row_alpha.refresh_from_db()
        row_beta.refresh_from_db()
        self.assertEqual(row_alpha.referee_state[str(org_a.id)]["first_event_sent"], True)
        self.assertEqual(row_beta.referee_state[str(org_b.id)]["first_event_sent"], False)

        Team.objects.filter(organization=org_b).update(ingested_event=True)

        execute_referral_ingestion_stage_sweep()
        row_beta.refresh_from_db()
        self.assertEqual(row_beta.referee_state[str(org_b.id)]["first_event_sent"], True)

    def test_failure_blob_recorded_and_cleared_on_successful_check(self) -> None:
        referee_org = Organization.objects.create(name="Referee meta clear")
        Team.objects.create(organization=referee_org, name="Tm", ingested_event=False)

        referral = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={str(referee_org.id): {"first_event_sent": False}},
        )

        self.assertTrue(record_ingestion_check_failure_on_referral_sync(referral.id, "unit_test_failure"))
        referral.refresh_from_db()
        state = referral.referee_state
        self.assertIsInstance(state, dict)
        errors = state[REFEREE_STATE_ERRORS_KEY]
        self.assertIsInstance(errors, dict)
        meta = errors[REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY]
        self.assertIsInstance(meta, dict)
        self.assertEqual(meta["last_failure_detail"], "unit_test_failure")
        self.assertIn("last_failure_at", meta)

        process_single_social_referral_ingestion_sync(referral.id)
        referral.refresh_from_db()
        state = referral.referee_state
        self.assertIsInstance(state, dict)
        self.assertNotIn(REFEREE_STATE_ERRORS_KEY, state)

    def test_errors_object_is_not_treated_as_referee_org(self) -> None:
        SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={
                REFEREE_STATE_ERRORS_KEY: {
                    REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY: {
                        "last_failure_at": "2026-01-01T00:00:00+00:00",
                        "last_failure_detail": "x",
                    },
                },
            },
        )

        snapshot = build_pending_ingestion_snapshot()
        self.assertEqual(snapshot["referral_ids"], [])
        self.assertEqual(snapshot["pending_referee_org_count"], 0)

    def test_clearing_ingestion_sync_preserves_other_errors_entries(self) -> None:
        referral = SocialReferral.objects.create(
            organization=self.organization,
            user=self.user,
            referee_state={
                REFEREE_STATE_ERRORS_KEY: {
                    REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY: {
                        "last_failure_at": "2026-01-01T00:00:00+00:00",
                        "last_failure_detail": "sync failed",
                    },
                    "other": {"msg": "keep me"},
                },
            },
        )

        process_single_social_referral_ingestion_sync(referral.id)
        referral.refresh_from_db()
        state = referral.referee_state
        self.assertIsInstance(state, dict)
        errors = state[REFEREE_STATE_ERRORS_KEY]
        self.assertIsInstance(errors, dict)
        self.assertNotIn(REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY, errors)
        self.assertEqual(errors["other"], {"msg": "keep me"})
