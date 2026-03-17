from products.notifications.backend.facade.enums import TargetType


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
        else:
            return []
