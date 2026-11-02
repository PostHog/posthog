import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.organization import OrganizationMembership
from posthog.models.scoping import reset_current_team_id, set_current_team_id

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.default_owner import assign_default_owner, resolve_default_owner
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutRun,
    SignalSourceConfig,
    SignalTeamConfig,
)
from products.skills.backend.models.skills import LLMSkill, LLMSkillOwner


class TestDefaultOwner(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(team=self.team, status="ready", title="A report")

    def _member(self, email: str, *, active: bool = True, level: int = OrganizationMembership.Level.MEMBER) -> User:
        user = User.objects.create(email=email, is_active=active)
        OrganizationMembership.objects.create(user=user, organization=self.organization, level=level)
        return user

    def _make_project_private(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )

    def _deny_reports_for(self, user: User) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save(update_fields=["available_product_features"])
        AccessControl.objects.create(
            team=self.team,
            resource="task",
            access_level="none",
            organization_member=OrganizationMembership.objects.get(organization=self.organization, user=user),
        )

    def _activated_by(self, user: User) -> None:
        SignalTeamConfig.objects.update_or_create(team=self.team, defaults={"onboarding": {"activated_by": user.pk}})

    def _enabled_source(self, user: User) -> None:
        SignalSourceConfig.objects.create(
            team=self.team, source_product="error_tracking", source_type="issue_created", created_by=user
        )

    def _authored_by_scout_of(self, user: User) -> None:
        LLMSkill.objects.create(team=self.team, name="signals-scout-general", description="d", body="b")
        config = SignalScoutConfig.objects.create(team=self.team, skill_name="signals-scout-general", created_by=user)
        task = apps.get_model("tasks", "Task").objects.create(team=self.team, title="scout", description="d")
        task_run = apps.get_model("tasks", "TaskRun").objects.create(team=self.team, task=task)
        SignalScoutRun.objects.create(
            team=self.team,
            task_run=task_run,
            scout_config=config,
            skill_name=config.skill_name,
            skill_version=1,
            emitted_report_ids=[str(self.report.id)],
        )

    def _reviewers(self, content: list[dict], *, by: User | None = None) -> None:
        SignalReportArtefact.objects.create(
            team=self.team,
            report=self.report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps(content),
            actor_kind="user" if by else "system",
            created_by=by,
        )

    def _latest_reviewers(self) -> list[dict]:
        latest = (
            SignalReportArtefact.objects.filter(
                report=self.report, type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS
            )
            .order_by("-created_at", "-id")
            .first()
        )
        return json.loads(latest.content) if latest else []

    @parameterized.expand(
        [
            ("skill_owner_before_whoever_enabled_the_scout", True, True, True, "skill_owner"),
            ("scout_owner_before_activator", True, False, True, "scout"),
            ("activator_before_enabler", False, False, True, "activator"),
            ("enabler_when_activator_is_deactivated", False, False, False, "enabler"),
        ]
    )
    def test_picks_the_first_eligible_candidate(
        self, _name: str, from_scout: bool, scout_has_owner: bool, activator_active: bool, expected: str
    ) -> None:
        people = {
            "skill_owner": self._member("skill-owner@example.com"),
            "scout": self._member("scout-owner@example.com"),
            "activator": self._member("activator@example.com", active=activator_active),
            "enabler": self._member("enabler@example.com"),
        }
        if from_scout:
            self._authored_by_scout_of(people["scout"])
        if scout_has_owner:
            LLMSkillOwner.objects.create(team=self.team, skill_name="signals-scout-general", user=people["skill_owner"])
        self._activated_by(people["activator"])
        self._enabled_source(people["enabler"])

        owner = resolve_default_owner(self.team, str(self.report.id))

        assert owner is not None
        assert owner.id == people[expected].id

    def test_falls_through_to_an_admin_when_the_enabler_cannot_see_the_project(self) -> None:
        self._make_project_private()
        enabler = self._member("enabler@example.com")
        self._member("admin@example.com", level=OrganizationMembership.Level.ADMIN)
        self._enabled_source(enabler)

        owner = resolve_default_owner(self.team, str(self.report.id))

        assert owner is not None
        assert owner.id != enabler.id

    def test_skips_a_candidate_who_cannot_read_reports(self) -> None:
        # Project access is not report access: the entry puts the report in front of whoever it names,
        # so a candidate whose report access was revoked must be passed over for the next one.
        enabler = self._member("enabler@example.com")
        admin = self._member("admin@example.com", level=OrganizationMembership.Level.ADMIN)
        self._enabled_source(enabler)
        self._deny_reports_for(enabler)

        owner = resolve_default_owner(self.team, str(self.report.id))

        assert owner is not None
        assert owner.id == admin.id

    def test_assigns_an_owner_outside_team_scope(self) -> None:
        self._authored_by_scout_of(self._member("scout-owner@example.com"))
        self._reviewers([])
        token = set_current_team_id(None)

        try:
            with patch("products.signals.backend.default_owner.default_owner_fallback_enabled", return_value=True):
                assert assign_default_owner(self.team, str(self.report.id)) is True
        finally:
            reset_current_team_id(token)

        (entry,) = self._latest_reviewers()
        assert entry["is_default_owner"] is True

    @parameterized.expand([("legacy_writer", False), ("protected_writer", True)])
    def test_routes_a_report_with_no_reviewers_to_the_default_owner(self, _name: str, writer_enabled: bool) -> None:
        self._activated_by(self.user)
        self._reviewers([])

        with (
            patch("products.signals.backend.default_owner.default_owner_fallback_enabled", return_value=True),
            patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=writer_enabled),
        ):
            assert assign_default_owner(self.team, str(self.report.id)) is True

        (entry,) = self._latest_reviewers()
        assert entry["user_uuid"] == str(self.user.uuid)
        assert entry["is_default_owner"] is True

    @parameterized.expand([("code_available", True, False), ("no_code_access", False, True)])
    def test_assigns_only_when_self_driving_cannot_read_code(self, _name: str, has_code: bool, assigned: bool) -> None:
        self._activated_by(self.user)
        self._reviewers([])

        with (
            patch("products.signals.backend.default_owner.default_owner_fallback_enabled", return_value=True),
            patch("products.signals.backend.default_owner.team_has_code_access", return_value=has_code),
        ):
            assert assign_default_owner(self.team, str(self.report.id)) is assigned

        assert bool(self._latest_reviewers()) is assigned

    @parameterized.expand([("evidence_reviewer_exists", False), ("person_removed_the_default_owner", True)])
    def test_leaves_the_report_alone(self, _name: str, person_removed_default_owner: bool) -> None:
        self._activated_by(self.user)
        teammate = self._member("teammate@example.com")
        if person_removed_default_owner:
            self._reviewers([{"user_uuid": str(self.user.uuid), "is_default_owner": True}])
            self._reviewers([], by=self.user)
        else:
            self._reviewers([{"user_uuid": str(teammate.uuid)}])
        before = self._latest_reviewers()

        with patch("products.signals.backend.default_owner.default_owner_fallback_enabled", return_value=True):
            assert assign_default_owner(self.team, str(self.report.id)) is False

        assert self._latest_reviewers() == before
