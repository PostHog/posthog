from typing import Union

from django.db import transaction

from django_scim import constants
from django_scim.adapters import SCIMGroup
from scim2_filter_parser.attr_paths import AttrPath

from posthog.models import OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain

from products.enterprise.backend.models.rbac.role import Role, RoleMembership


class PostHogSCIMGroup(SCIMGroup):
    """
    Adapter to map SCIM Group schema to PostHog RBAC Role model.
    SCIM Groups are mapped to PostHog Roles for organization-level permissions.
    """

    resource_type = "Group"

    # Attribute map for SCIM PATCH operation path parsing
    # Maps SCIM attribute paths to SCIM JSON paths for PATCH operations
    # NOT for database filtering - see SCIM_GROUP_ATTR_MAP in views.py for that
    # Each key is a tuple of (attribute, sub-attribute, schema URI)
    ATTR_MAP = {
        ("displayName", None, None): "displayName",
        ("members", None, None): "members",
        ("members", "value", None): "members.value",
        ("members", "display", None): "members.display",
    }

    @property
    def id(self) -> str:
        return str(self.obj.id)

    @property
    def display_name(self) -> str:
        return self.obj.name

    @property
    def members(self) -> list[dict]:
        """
        Return list of group members in SCIM format.
        """
        role_memberships = RoleMembership.objects.filter(role=self.obj).select_related("user")
        return [
            {
                "value": str(rm.user.id),
                "$ref": f"/scim/v2/{self._organization_domain.id}/Users/{rm.user.id}",
                "display": rm.user.email,
            }
            for rm in role_memberships
        ]

    def __init__(self, obj: Role, organization_domain: OrganizationDomain):
        super().__init__(obj)
        self._organization_domain = organization_domain

    @classmethod
    def resource_type_dict(cls, request=None) -> dict:
        return {
            "id": cls.resource_type,
            "name": cls.resource_type,
            "endpoint": f"/scim/v2/{request.auth.id if request and request.auth else '{domain_id}'}/Groups",
            "schema": constants.SchemaURI.GROUP,
        }

    def to_dict(self) -> dict:
        """
        Convert Role to SCIM Group format.
        """
        return {
            "id": self.id,
            "displayName": self.display_name,
            "members": self.members,
            "meta": {
                "resourceType": self.resource_type,
                "location": f"/scim/v2/{self._organization_domain.id}/Groups/{self.id}",
            },
        }

    @classmethod
    def from_dict(cls, data: dict, organization_domain: OrganizationDomain) -> "PostHogSCIMGroup":
        """
        Create or update a Role from SCIM Group data.
        Upserts role by name matching.
        """
        display_name = data.get("displayName")
        if not display_name:
            raise ValueError("displayName is required for groups")

        with transaction.atomic():
            # Upsert role by name
            role, created = Role.objects.get_or_create(
                name=display_name,
                organization=organization_domain.organization,
                defaults={"created_by": None},
            )

            # Handle member updates if provided
            if "members" in data:
                cls._update_members(role, data["members"], organization_domain)

        return cls(role, organization_domain)

    @classmethod
    def _update_members(cls, role: Role, members_data: list[dict], organization_domain: OrganizationDomain) -> None:
        """
        Update role membership based on SCIM members list.
        """
        # Get list of user IDs from SCIM data
        member_user_ids = {member.get("value") for member in members_data}

        # Get current role members
        current_memberships = RoleMembership.objects.filter(role=role).select_related("user", "organization_member")

        current_user_ids = {str(rm.user.id) for rm in current_memberships}
        to_add = member_user_ids - current_user_ids
        to_remove = current_user_ids - member_user_ids

        for user_id in to_add:
            try:
                user = User.objects.get(id=user_id)
                org_membership = OrganizationMembership.objects.filter(
                    user=user, organization=organization_domain.organization
                ).first()

                if org_membership:
                    RoleMembership.objects.get_or_create(
                        role=role, user=user, defaults={"organization_member": org_membership}
                    )
            except User.DoesNotExist:
                continue

        # Remove members no longer in the group
        RoleMembership.objects.filter(role=role, user__id__in=to_remove).delete()

    def put(self, data: dict) -> None:
        """
        Handle PUT operation - completely replace group.

        Any attributes not provided are cleared.
        """
        display_name = data.get("displayName")
        if not display_name:
            raise ValueError("displayName is required for groups")

        with transaction.atomic():
            self.obj.name = display_name
            self.obj.save()

            members_data = data.get("members", [])
            self._update_members(self.obj, members_data, self._organization_domain)

    def delete(self) -> None:
        """
        Delete the role.
        """
        self.obj.delete()

    def handle_replace(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH replace operations (called by django-scim2 handle_operations).

        Replace group name or members.
        """
        first_path = path.first_path
        attr_name = first_path.attr_name

        with transaction.atomic():
            if attr_name == "displayName":
                self.obj.name = value
                self.obj.save()

            elif attr_name == "members":
                if path.is_complex:
                    raise ValueError("Complex filtered paths for members are not supported")
                else:
                    members_data = value if isinstance(value, list) else [value]
                    self._update_members(self.obj, members_data, self._organization_domain)

    def handle_add(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH add operations (called by django-scim2 handle_operations).

        Add members to a group without replacing existing members.
        """
        first_path = path.first_path
        attr_name = first_path.attr_name

        with transaction.atomic():
            if attr_name == "displayName":
                # Add operation for displayName acts like replace
                self.obj.name = value
                self.obj.save()

            elif attr_name == "members":
                if path.is_complex:
                    # Handle filtered path: members[value eq "<user-id>"]
                    user_id = path.params_by_attr_paths.get(("members", "value", None))
                    if user_id:
                        members_to_add = [{"value": user_id}]
                elif isinstance(value, list):
                    members_to_add = value
                elif isinstance(value, dict):
                    members_to_add = [value]
                elif isinstance(value, str):
                    members_to_add = [{"value": value}]

                for member_data in members_to_add:
                    user_id = member_data.get("value")

                    try:
                        user = User.objects.get(id=user_id)
                        # Upsert organization membership
                        org_membership, _ = OrganizationMembership.objects.get_or_create(
                            user=user,
                            organization=self._organization_domain.organization,
                            defaults={"level": OrganizationMembership.Level.MEMBER},
                        )

                        RoleMembership.objects.get_or_create(
                            role=self.obj, user=user, defaults={"organization_member": org_membership}
                        )
                    except User.DoesNotExist:
                        continue

    def handle_remove(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH remove operations (called by django-scim2 handle_operations).

        Remove members from a group. Reject removing group name.
        """
        first_path = path.first_path
        attr_name = first_path.attr_name

        with transaction.atomic():
            if attr_name == "displayName":
                raise ValueError("Group name cannot be removed")

            elif attr_name == "members":
                if path.is_complex:
                    # Path like: members[value eq "<user-id>"]
                    user_id = path.params_by_attr_paths.get(("members", "value", None))
                    if user_id:
                        RoleMembership.objects.filter(role=self.obj, user__id=str(user_id)).delete()
                else:
                    # Simple path, remove all members
                    RoleMembership.objects.filter(role=self.obj).delete()

    @classmethod
    def get_for_organization(cls, organization_domain: OrganizationDomain) -> list["PostHogSCIMGroup"]:
        """
        Get all roles (groups) for a specific organization.
        """
        roles = Role.objects.filter(organization=organization_domain.organization)
        return [cls(role, organization_domain) for role in roles]
