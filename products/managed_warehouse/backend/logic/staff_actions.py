"""Warehouse lifecycle actions that staff run by hand, from PostHog Admin or Django admin.

They run the same flows as the in-product API, without the organization's feature flag, so staff can act
before the organization has the in-product UI.
"""

import dataclasses
from uuid import UUID

import structlog
import posthoganalytics

from posthog.models import Organization, Team

from products.managed_warehouse.backend.facade.contracts import (
    DuckgresServerSummary,
    ProvisionedWarehouseLogin,
    StaffActionOutcome,
    StaffProvisionPreview,
)
from products.managed_warehouse.backend.logic.access import is_internal_warehouse
from products.managed_warehouse.backend.models import DuckgresServer, ManagedWarehouseSourceLifecycle

logger = structlog.get_logger(__name__)


def get_duckgres_server_summary(organization_id: UUID) -> DuckgresServerSummary | None:
    server = DuckgresServer.objects.filter(organization_id=organization_id).first()
    if server is None:
        return None
    # Deprovisioning keeps the server row and only marks the lifecycle inactive. A missing lifecycle row
    # means the warehouse predates the lifecycle and is still active.
    deprovisioned = ManagedWarehouseSourceLifecycle.objects.filter(
        organization_id=organization_id, desired_active=False
    ).exists()
    return DuckgresServerSummary(
        server_id=server.pk,
        host=server.host,
        bucket=server.bucket,
        internal_testing=is_internal_warehouse(organization_id),
        deprovisioned=deprovisioned,
    )


def organization_id_for_duckgres_server(server_id: UUID) -> UUID | None:
    return DuckgresServer.objects.filter(pk=server_id).values_list("organization_id", flat=True).first()


class StaffActions:
    """Runs one staff action and reports it the same way from every entry point: an analytics event when it
    starts and when it ends, and a log line with the actor when it fails. The views log successes themselves."""

    def __init__(self, *, actor_email: str, actor_distinct_id: str) -> None:
        self.actor_email = actor_email
        self.actor_distinct_id = actor_distinct_id

    @property
    def audit_principal(self) -> str:
        return f"django-admin:{self.actor_email}"

    def track(self, action: str, status_code: int | None) -> None:
        try:
            posthoganalytics.capture(
                distinct_id=self.actor_distinct_id,
                event="managed warehouse admin action started"
                if status_code is None
                else "managed warehouse admin action completed",
                properties={"action": action, "success": status_code is not None and 200 <= status_code < 300},
            )
        except Exception:
            logger.warning("managed_warehouse_admin_tracking_failed", action=action)

    @staticmethod
    def resolve_team(organization_id: str, team_id: str) -> Team | str:
        """The team, or why it cannot be used: the team must belong to the given organization."""
        if not organization_id or not team_id:
            return "Organization and team are both required."
        if not Organization.objects.filter(pk=organization_id).exists():
            return f"No organization with id {organization_id}."
        team = Team.objects.filter(pk=team_id).first() if team_id.isdigit() else None
        if team is None:
            return f"No team with id {team_id}."
        if str(team.organization_id) != str(organization_id):
            return f"Team {team_id} does not belong to organization {organization_id}."
        return team

    def outcome(self, action: str, response, success_message: str) -> StaffActionOutcome:
        self.track(action, response.status_code)
        if 200 <= response.status_code < 300:
            return StaffActionOutcome(
                ok=True, status_code=response.status_code, message=f"{success_message}. (status {response.status_code})"
            )
        detail = response.data.get("error") if isinstance(response.data, dict) else response.data
        logger.warning(
            "admin_managed_warehouse_action_failed",
            action=success_message,
            triggered_by=self.audit_principal,
            status_code=response.status_code,
            error=detail,
        )
        return StaffActionOutcome(
            ok=False, status_code=response.status_code, message=f"Failed (status {response.status_code}): {detail}"
        )

    def onboard_team(self, organization_id: UUID, team_id: int, schema_name: str) -> StaffActionOutcome:
        from products.managed_warehouse.backend.presentation import views as managed_warehouse  # noqa: PLC0415

        self.track("enable-backfill", None)
        team = self.resolve_team(str(organization_id), str(team_id))
        if isinstance(team, str):
            return StaffActionOutcome(ok=False, status_code=400, message=team)
        response = managed_warehouse.onboard_team(
            organization_id,
            team.id,
            schema_name,
            require_enabled=False,
            triggered_by=self.audit_principal,
        )
        return self.outcome("enable-backfill", response, f"Onboarded team {team.id} onto the managed warehouse")

    def deprovision(self, organization_id: UUID) -> StaffActionOutcome:
        from products.managed_warehouse.backend.presentation import views as managed_warehouse  # noqa: PLC0415

        self.track("deprovision", None)
        response = managed_warehouse.deprovision(
            organization_id, require_enabled=False, triggered_by=self.audit_principal
        )
        return self.outcome("deprovision", response, f"Deprovisioned managed warehouse for org {organization_id}")

    @classmethod
    def preview_provision(cls, organization_id: UUID, team_id: int, database_name: str) -> StaffProvisionPreview:
        from products.managed_warehouse.backend.presentation import views as managed_warehouse  # noqa: PLC0415

        host = managed_warehouse._present_connection({"database": database_name})["host"]
        team = cls.resolve_team(str(organization_id), str(team_id))
        if isinstance(team, str):
            return StaffProvisionPreview(team_name="", host=host, problem=team)
        return StaffProvisionPreview(team_name=team.name, host=host)

    def provision(
        self, organization_id: UUID, team_id: int, database_name: str, schema_name: str, *, internal_only: bool
    ) -> StaffActionOutcome:
        from products.managed_warehouse.backend.presentation import views as managed_warehouse  # noqa: PLC0415

        self.track("provision", None)
        team = self.resolve_team(str(organization_id), str(team_id))
        if isinstance(team, str):
            return StaffActionOutcome(ok=False, status_code=400, message=team)
        response = managed_warehouse.provision(
            team.organization_id,
            database_name,
            team.id,
            schema_name,
            require_enabled=False,
            triggered_by=self.audit_principal,
            internal_only=internal_only,
        )
        outcome = self.outcome("provision", response, f"Provisioned managed warehouse for org {team.organization_id}")
        if not outcome.ok:
            return outcome
        body = response.data if isinstance(response.data, dict) else {}
        connection = managed_warehouse._present_connection(
            {"database": database_name, "username": body.get("username", "root")}
        )
        login = ProvisionedWarehouseLogin(
            host=connection["host"],
            port=connection["port"],
            database=connection["database"],
            username=connection["username"],
            password=body.get("password", ""),
        )
        return dataclasses.replace(outcome, login=login)
