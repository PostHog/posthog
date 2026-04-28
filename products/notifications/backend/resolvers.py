from typing import cast

import structlog

from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.scopes import APIScopeObject

from products.notifications.backend.facade.enums import TargetType

logger = structlog.get_logger(__name__)


class RecipientsResolver:
    def resolve(self, target_type: TargetType, target_id: str, team_id: int) -> list[int]:
        if target_type == TargetType.USER:
            return [int(target_id)]
        elif target_type == TargetType.TEAM:
            from posthog.models import OrganizationMembership

            return list(
                OrganizationMembership.objects.filter(
                    organization__teams__id=int(target_id),
                ).values_list("user_id", flat=True)
            )
        elif target_type == TargetType.ORGANIZATION:
            from posthog.models import OrganizationMembership

            return list(
                OrganizationMembership.objects.filter(
                    organization_id=target_id,
                ).values_list("user_id", flat=True)
            )
        elif target_type == TargetType.ROLE:
            from ee.models.rbac.role import RoleMembership

            return list(
                RoleMembership.objects.filter(
                    role_id=target_id,
                ).values_list("user_id", flat=True)
            )

        raise ValueError(f"Unknown target type: {target_type}")

    def filter_by_access_control(self, user_ids: list[int], resource_type: str, team: Team) -> list[int]:
        """Filter user IDs by access control. Not overridable — always applied after resolve()."""
        try:
            sample_user = User.objects.filter(id__in=user_ids).first()
            if not sample_user:
                return user_ids
            sample_ac = UserAccessControl(sample_user, team)
            if not sample_ac.access_controls_supported:
                return user_ids
        except Exception:
            logger.exception("notifications.ac_check_failed")
            return user_ids

        filtered = []
        # TODO: optimize for large orgs — batch AC checks instead of per-user
        users = User.objects.filter(id__in=user_ids)
        for user in users:
            ac = UserAccessControl(user, team)
            if ac.check_access_level_for_resource(cast(APIScopeObject, resource_type), "viewer"):
                filtered.append(user.id)
        return filtered
