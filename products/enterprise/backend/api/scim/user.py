from typing import Optional, Union

from django.db import transaction

from django_scim import constants
from django_scim.adapters import SCIMUser
from scim2_filter_parser.attr_paths import AttrPath

from posthog.models import OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain

from products.enterprise.backend.models.rbac.role import RoleMembership


class PostHogSCIMUser(SCIMUser):
    """
    Adapter to map SCIM User schema to PostHog User model.
    Handles user provisioning scoped to a specific OrganizationDomain.
    """

    resource_type = "User"

    # Attribute map for SCIM PATCH operation path parsing
    # Maps SCIM attribute paths to SCIM JSON paths for PATCH operations
    # NOT for database filtering - see SCIM_USER_ATTR_MAP in views.py for that
    # Each key is a tuple of (attribute, sub-attribute, schema URI)
    ATTR_MAP = {
        ("userName", None, None): "userName",
        ("name", "givenName", None): "name.givenName",
        ("name", "familyName", None): "name.familyName",
        ("emails", None, None): "emails",
        ("emails", "value", None): "emails.value",
        ("emails", "type", None): "emails.type",
        ("emails", "primary", None): "emails.primary",
        ("active", None, None): "active",
    }

    @property
    def id(self) -> str:
        return str(self.obj.id)

    @property
    def display_name(self) -> Optional[str]:
        full_name = f"{self.obj.first_name} {self.obj.last_name}".strip()
        return full_name if full_name else None

    @property
    def emails(self) -> list[dict]:
        return [{"value": self.obj.email, "primary": True}]

    @property
    def name(self) -> dict:
        return {"givenName": self.obj.first_name or "", "familyName": self.obj.last_name or ""}

    @property
    def user_name(self) -> str:
        return self.obj.email

    @property
    def active(self) -> bool:
        # A user is "active" in SCIM context if they have membership in this org
        if not hasattr(self, "_organization_domain"):
            return self.obj.is_active
        return OrganizationMembership.objects.filter(
            user=self.obj, organization=self._organization_domain.organization
        ).exists()

    def __init__(self, obj: User, organization_domain: OrganizationDomain):
        super().__init__(obj)
        self._organization_domain = organization_domain

    @staticmethod
    def _extract_email_from_value(emails: list[dict]) -> Optional[str]:
        """
        Extract email from SCIM emails array.
        Returns primary email if available, otherwise first email.
        """
        if not emails:
            return None
        primary_email = next((e["value"] for e in emails if e.get("primary")), None)
        return primary_email or emails[0]["value"]

    @classmethod
    def resource_type_dict(cls, request=None) -> dict:
        return {
            "id": cls.resource_type,
            "name": cls.resource_type,
            "endpoint": f"/scim/v2/{request.auth.id if request and request.auth else '{domain_id}'}/Users",
            "schema": constants.SchemaURI.USER,
        }

    def to_dict(self) -> dict:
        """
        Convert User to SCIM format.
        """
        base_dict = {
            "id": self.id,
            "userName": self.user_name,
            "name": self.name,
            "emails": self.emails,
            "active": self.active,
            "meta": {
                "resourceType": self.resource_type,
                "location": f"/scim/v2/{self._organization_domain.id}/Users/{self.id}",
            },
        }

        if self.display_name:
            base_dict["displayName"] = self.display_name

        role_memberships = RoleMembership.objects.filter(
            user=self.obj, role__organization=self._organization_domain.organization
        ).select_related("role")
        base_dict["groups"] = [
            {
                "value": str(rm.role.id),
                "$ref": f"/scim/v2/{self._organization_domain.id}/Groups/{rm.role.id}",
                "display": rm.role.name,
            }
            for rm in role_memberships
        ]

        return base_dict

    @classmethod
    def from_dict(cls, data: dict, organization_domain: OrganizationDomain) -> "PostHogSCIMUser":
        """
        Create or update a User from SCIM data.
        """
        email = cls._extract_email_from_value(data.get("emails", []))
        if not email:
            raise ValueError("email is required")

        name_data = data.get("name", {})
        first_name = name_data.get("givenName", "")
        last_name = name_data.get("familyName", "")

        with transaction.atomic():
            user = User.objects.filter(email__iexact=email).first()

            if user:
                if first_name:
                    user.first_name = first_name
                if last_name:
                    user.last_name = last_name
                user.save()
            else:
                # Create new user with no password (they'll use SAML)
                user = User.objects.create_user(
                    email=email, password=None, first_name=first_name, last_name=last_name, is_email_verified=True
                )

            # Ensure user has membership in this organization
            OrganizationMembership.objects.get_or_create(
                user=user,
                organization=organization_domain.organization,
                defaults={"level": OrganizationMembership.Level.MEMBER},
            )

            # Set current org/team if this is their first org
            if not user.current_organization:
                user.current_organization = organization_domain.organization
                user.current_team = organization_domain.organization.teams.first()
                user.save()

        return cls(user, organization_domain)

    def put(self, data: dict) -> None:
        """
        Handle SCIM PUT operation, completely replace user.

        Any attributes not provided are cleared.
        """
        name_data = data.get("name", {})
        email = self._extract_email_from_value(data.get("emails", []))

        if not email:
            raise ValueError("Email is required")

        with transaction.atomic():
            # Do not allow changing email to another user's email
            existing_user_with_email = User.objects.filter(email__iexact=email).exclude(id=self.obj.id).first()
            if existing_user_with_email:
                raise ValueError("Email belongs to another user")

            self.obj.first_name = name_data.get("givenName", "")
            self.obj.last_name = name_data.get("familyName", "")
            self.obj.email = email
            self.obj.save()

            # Deactivate user if active is false
            is_active = data.get("active", True)
            if not is_active:
                self.delete()

    def delete(self) -> None:
        """
        Deactivate user by removing their membership from this organization.
        """
        OrganizationMembership.objects.filter(
            user=self.obj, organization=self._organization_domain.organization
        ).delete()

    def handle_replace(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH replace operations (called by django-scim2 handle_operations).

        Each attribute update comes as a separate call with its specific path and value.
        Supports complex paths like 'emails[type eq "work"].value' via scim2-filter-parser.
        """
        first_path = path.first_path
        attr_name = first_path.attr_name
        sub_attr = first_path.sub_attr

        with transaction.atomic():
            if attr_name == "active":
                if not value:
                    self.delete()

            elif attr_name == "name":
                if sub_attr == "givenName" and isinstance(value, str):
                    self.obj.first_name = value
                elif sub_attr == "familyName" and isinstance(value, str):
                    self.obj.last_name = value
                elif isinstance(value, dict):
                    if "givenName" in value:
                        self.obj.first_name = value["givenName"]
                    if "familyName" in value:
                        self.obj.last_name = value["familyName"]

            elif attr_name == "emails":
                email = None
                if path.is_complex and isinstance(value, str):
                    email = value
                elif isinstance(value, list):
                    email = self._extract_email_from_value(value)

                if email:
                    self.obj.email = email

            self.obj.save()

    def handle_add(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH add operations (called by django-scim2 handle_operations).
        """
        first_path = path.first_path
        attr_name = first_path.attr_name
        sub_attr = first_path.sub_attr

        with transaction.atomic():
            if attr_name == "active" and value:
                OrganizationMembership.objects.get_or_create(
                    user=self.obj,
                    organization=self._organization_domain.organization,
                    defaults={"level": OrganizationMembership.Level.MEMBER},
                )

            elif attr_name == "name":
                if sub_attr == "givenName" and isinstance(value, str):
                    self.obj.first_name = value
                elif sub_attr == "familyName" and isinstance(value, str):
                    self.obj.last_name = value
                elif isinstance(value, dict):
                    if "givenName" in value:
                        self.obj.first_name = value["givenName"]
                    if "familyName" in value:
                        self.obj.last_name = value["familyName"]
                self.obj.save()

            elif attr_name == "emails":
                email = None
                if path.is_complex and isinstance(value, str):
                    email = value
                elif isinstance(value, list):
                    email = self._extract_email_from_value(value)

                if email:
                    self.obj.email = email
                    self.obj.save()

    def handle_remove(self, path: AttrPath, value: Union[str, list, dict], operation: dict) -> None:
        """
        Handle SCIM PATCH remove operations (called by django-scim2 handle_operations).
        """
        first_path = path.first_path
        attr_name = first_path.attr_name
        sub_attr = first_path.sub_attr

        with transaction.atomic():
            if attr_name == "active":
                self.delete()

            elif attr_name == "name":
                if sub_attr == "givenName":
                    self.obj.first_name = ""
                elif sub_attr == "familyName":
                    self.obj.last_name = ""
                elif not sub_attr:
                    self.obj.first_name = ""
                    self.obj.last_name = ""
                self.obj.save()

            elif attr_name == "emails":
                raise ValueError("Email is required and cannot be removed")

    @classmethod
    def get_for_organization(cls, organization_domain: OrganizationDomain) -> list["PostHogSCIMUser"]:
        """
        Get all users for a specific organization domain.
        """
        users = User.objects.filter(organization_membership__organization=organization_domain.organization)
        return [cls(user, organization_domain) for user in users]
