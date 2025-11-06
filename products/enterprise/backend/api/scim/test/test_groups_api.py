import uuid

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain

from products.enterprise.backend.api.scim.auth import generate_scim_token
from products.enterprise.backend.api.test.base import APILicensedTest
from products.enterprise.backend.models.rbac.role import Role, RoleMembership


class TestSCIMGroupsAPI(APILicensedTest):
    def setUp(self):
        super().setUp()

        # Ensure SCIM is in available features
        if not self.organization.is_feature_available(AvailableFeature.SCIM):
            features = self.organization.available_product_features or []
            if not any(f.get("key") == AvailableFeature.SCIM for f in features):
                features.append({"key": AvailableFeature.SCIM, "name": "SCIM"})
            self.organization.available_product_features = features
            self.organization.save()

        # Create organization domain with SCIM enabled
        self.domain = OrganizationDomain.objects.create(
            organization=self.organization,
            domain="example.com",
            verified_at="2024-01-01T00:00:00Z",
        )

        # Generate SCIM token
        self.plain_token, hashed_token = generate_scim_token()
        self.domain.scim_enabled = True
        self.domain.scim_bearer_token = hashed_token
        self.domain.save()

        self.scim_headers = {"HTTP_AUTHORIZATION": f"Bearer {self.plain_token}"}
        self.client.credentials(**self.scim_headers)

    def test_groups_list(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Groups")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "Resources" in data

    def test_groups_list_filter_exact_match(self):
        Role.objects.create(name="Engineering", organization=self.organization)
        Role.objects.create(name="engineering", organization=self.organization)
        Role.objects.create(name="Marketing", organization=self.organization)
        Role.objects.create(name="Sales", organization=self.organization)

        # Filter for exact match on displayName
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Groups",
            {"filter": 'displayName eq "Engineering"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 1
        assert data["itemsPerPage"] == 1
        assert data["Resources"][0]["displayName"] == "Engineering"

    def test_groups_list_filter_excludes_groups_from_other_orgs(self):
        # Create role with same name in different organization
        other_org = Organization.objects.create(name="Other Org")
        Role.objects.create(name="Engineering", organization=other_org)

        # Filter for role from other org should return nothing
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Groups",
            {"filter": 'displayName eq "Engineering"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 0
        assert data["Resources"] == []

    def test_groups_list_filter_no_match_returns_empty_list(self):
        Role.objects.create(name="Engineering", organization=self.organization)

        # Filter for non-existent group
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Groups",
            {"filter": 'displayName eq "NonExistent"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 0
        assert data["itemsPerPage"] == 0
        assert data["Resources"] == []

    def test_create_group(self):
        group_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "Engineering",
            "members": [],
        }

        response = self.client.post(f"/scim/v2/{self.domain.id}/Groups", data=group_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["displayName"] == "Engineering"

        # Verify role was created
        role = Role.objects.get(name="Engineering", organization=self.organization)
        assert role is not None

    def test_repeated_post_does_not_create_duplicate_group(self):
        # In case the IdP failed to match group by id, it can send POST request to create a new group.
        # The group should be merged with existing one by name, not create a duplicate.
        user = User.objects.create_user(
            email="groupmember@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        # IdP sends POST request to create group (first time)
        group_data_first = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "Developers",
            "members": [{"value": str(user.id)}],
        }

        response = self.client.post(f"/scim/v2/{self.domain.id}/Groups", data=group_data_first, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        first_role = Role.objects.get(name="Developers", organization=self.organization)
        assert RoleMembership.objects.filter(role=first_role, user=user).exists()

        # IdP sends POST request again with same displayName (second time)
        group_data_second = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "Developers",
            "members": [],
        }

        response = self.client.post(f"/scim/v2/{self.domain.id}/Groups", data=group_data_second, format="json")

        assert response.status_code == status.HTTP_201_CREATED

        # Should NOT create duplicate group
        assert Role.objects.filter(name="Developers", organization=self.organization).count() == 1

        # Members should be updated (removed in second POST)
        assert not RoleMembership.objects.filter(role=first_role, user=user).exists()

    def test_put_group(self):
        user = User.objects.create_user(
            email="groupmember@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="OldName", organization=self.organization)

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "NewName",
            "members": [{"value": str(user.id)}],
        }

        response = self.client.put(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=put_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "NewName"
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_put_group_not_found(self):
        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "displayName": "ShouldFail",
            "members": [],
        }

        fake_group_id = str(uuid.uuid4())
        response = self.client.put(f"/scim/v2/{self.domain.id}/Groups/{fake_group_id}", data=put_data, format="json")

        assert (
            response.status_code == status.HTTP_404_NOT_FOUND
        ), f"Expected 404, got {response.status_code}: {response.content}"
        assert not Role.objects.filter(name="ShouldFail", organization=self.organization).exists()

    def test_patch_group_not_found(self):
        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"displayName": "ShouldFail"}}],
        }

        fake_group_id = str(uuid.uuid4())
        response = self.client.patch(
            f"/scim/v2/{self.domain.id}/Groups/{fake_group_id}", data=patch_data, format="json"
        )

        assert (
            response.status_code == status.HTTP_404_NOT_FOUND
        ), f"Expected 404, got {response.status_code}: {response.content}"

    def test_patch_replace_group_without_path(self):
        user = User.objects.create_user(
            email="groupreplace@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="OldGroupName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "value": {"displayName": "NewGroupName", "members": [{"value": str(user.id)}]}}
            ],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "NewGroupName"
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_patch_replace_group_display_name_with_simple_path(self):
        role = Role.objects.create(name="OldName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "displayName", "value": "UpdatedName"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "UpdatedName"

    def test_patch_replace_group_members_with_simple_path(self):
        user = User.objects.create_user(
            email="groupmembers@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "members", "value": [{"value": str(user.id)}]}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_patch_replace_group_member_with_filtered_path_not_supported(self):
        # Swapping members within a group with a filtered path is not supported
        # Most IdPs send remove and add operations separately in this case
        user1 = User.objects.create_user(
            email="filteredmember1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="filteredmember2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=user1,
            organization_member=OrganizationMembership.objects.get(user=user1, organization=self.organization),
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": f'members[value eq "{user1.id}"].value', "value": str(user2.id)}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert RoleMembership.objects.filter(role=role, user=user1).exists()
        assert not RoleMembership.objects.filter(role=role, user=user2).exists()

    def test_patch_add_group_members_without_path(self):
        user = User.objects.create_user(
            email="addgroup@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="InitialName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "value": {"members": [{"value": str(user.id)}]}}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "InitialName"
        assert RoleMembership.objects.filter(role=role, user=user).exists()

    def test_patch_add_group_display_name_with_simple_path(self):
        role = Role.objects.create(name="OldName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "displayName", "value": "AddedName"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        role.refresh_from_db()
        assert role.name == "AddedName"

    def test_patch_add_group_members_with_simple_path(self):
        user1 = User.objects.create_user(
            email="addmember1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="addmember2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)

        RoleMembership.objects.create(
            role=role,
            user=user1,
            organization_member=OrganizationMembership.objects.get(user=user1, organization=self.organization),
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "members", "value": [{"value": str(user2.id)}]}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user1).exists()
        assert RoleMembership.objects.filter(role=role, user=user2).exists()

    def test_patch_add_group_member_with_filtered_path(self):
        user1 = User.objects.create_user(
            email="addfiltered1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="addfiltered2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": f'members[value eq "{user1.id}"]'}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert RoleMembership.objects.filter(role=role, user=user1).exists()

    def test_patch_remove_group_display_name_should_fail(self):
        role = Role.objects.create(name="RemoveName", organization=self.organization)

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "displayName"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        role.refresh_from_db()
        assert role.name == "RemoveName"

    def test_patch_remove_group_members_with_simple_path(self):
        user = User.objects.create_user(
            email="removeallmembers@example.com", password=None, first_name="Member", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=user,
            organization_member=OrganizationMembership.objects.get(user=user, organization=self.organization),
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "members"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role).exists()

    def test_patch_remove_group_member_with_filtered_path(self):
        user1 = User.objects.create_user(
            email="removefiltered1@example.com", password=None, first_name="Member1", is_email_verified=True
        )
        user2 = User.objects.create_user(
            email="removefiltered2@example.com", password=None, first_name="Member2", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user1, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        role = Role.objects.create(name="TestRole", organization=self.organization)
        RoleMembership.objects.create(
            role=role,
            user=user1,
            organization_member=OrganizationMembership.objects.get(user=user1, organization=self.organization),
        )
        RoleMembership.objects.create(
            role=role,
            user=user2,
            organization_member=OrganizationMembership.objects.get(user=user2, organization=self.organization),
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": f'members[value eq "{user1.id}"]'}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Groups/{role.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert not RoleMembership.objects.filter(role=role, user=user1).exists()
        assert RoleMembership.objects.filter(role=role, user=user2).exists()
