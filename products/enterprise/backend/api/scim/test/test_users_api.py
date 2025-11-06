from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, User
from posthog.models.organization_domain import OrganizationDomain

from products.enterprise.backend.api.scim.auth import generate_scim_token
from products.enterprise.backend.api.test.base import APILicensedTest
from products.enterprise.backend.models.rbac.role import RoleMembership


class TestSCIMUsersAPI(APILicensedTest):
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

    def test_users_list(self):
        response = self.client.get(f"/scim/v2/{self.domain.id}/Users")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "Resources" in data
        assert data["totalResults"] >= 1  # At least the test user

    def test_users_list_filter_exact_match(self):
        user_a = User.objects.create_user(
            email="engineering@example.com",
            password=None,
            first_name="Engineering",
            last_name="User",
            is_email_verified=True,
        )
        OrganizationMembership.objects.create(
            user=user_a, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        user_b = User.objects.create_user(
            email="alex@example.com", password=None, first_name="Alex", last_name="Other", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user_b, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        # Exact match should return only engineering@example.com
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Users",
            {"filter": 'userName eq "engineering@example.com"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 1
        assert data["itemsPerPage"] == 1
        assert data["Resources"][0]["userName"] == "engineering@example.com"

    def test_users_list_filter_excludes_users_from_other_orgs(self):
        # Create user that belongs only to a different organization
        other_org = Organization.objects.create(name="Other Org")
        user_other_org = User.objects.create_user(
            email="engineering@example.com",
            password=None,
            first_name="Other",
            last_name="User",
            is_email_verified=True,
        )
        OrganizationMembership.objects.create(
            user=user_other_org, organization=other_org, level=OrganizationMembership.Level.MEMBER
        )

        # Filter for user from other org should return nothing
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Users",
            {"filter": 'userName eq "engineering@example.com"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 0
        assert data["Resources"] == []

    def test_users_list_filter_no_match_returns_empty_list(self):
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Users",
            {"filter": 'userName eq "nonexistent@example.com"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 0
        assert data["itemsPerPage"] == 0
        assert data["Resources"] == []

    def test_users_list_filter_unrecognized_returns_empty_list(self):
        # Unsupported filter should not return all users; return empty set
        response = self.client.get(
            f"/scim/v2/{self.domain.id}/Users",
            {"filter": 'name.givenName sw "Eng"'},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["totalResults"] == 0
        assert data["itemsPerPage"] == 0
        assert data["Resources"] == []

    def test_create_user(self):
        user_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "newuser@example.com",
            "name": {"givenName": "New", "familyName": "User"},
            "emails": [{"value": "newuser@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.post(f"/scim/v2/{self.domain.id}/Users", data=user_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["userName"] == "newuser@example.com"
        assert data["name"]["givenName"] == "New"
        assert data["name"]["familyName"] == "User"

        # Verify user was created
        user = User.objects.get(email="newuser@example.com")
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert user.is_email_verified is True

        # Verify organization membership
        membership = OrganizationMembership.objects.get(user=user, organization=self.organization)
        assert membership.level == OrganizationMembership.Level.MEMBER

    def test_existing_user_is_added_to_org(self):
        # Create user in different org
        other_org = Organization.objects.create(name="Other Org")
        existing_user = User.objects.create_user(
            email="existing@example.com", password=None, first_name="Existing", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=existing_user, organization=other_org, level=OrganizationMembership.Level.MEMBER
        )

        # Try to provision same user via SCIM
        user_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "existing@example.com",
            "name": {"givenName": "Existing", "familyName": "User"},
            "emails": [{"value": "existing@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.post(f"/scim/v2/{self.domain.id}/Users", data=user_data, format="json")

        assert response.status_code == status.HTTP_201_CREATED

        # User should now be member of both orgs
        assert OrganizationMembership.objects.filter(user=existing_user, organization=self.organization).exists()
        assert OrganizationMembership.objects.filter(user=existing_user, organization=other_org).exists()

    def test_repeated_post_does_not_create_duplicate_user(self):
        # In case the IdP failed to match user by id, it can send POST request to create a new user.
        # The user should be merged with existing one by email, not create a duplicate.
        user_data_first = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "repeat@example.com",
            "name": {"givenName": "First", "familyName": "Time"},
            "emails": [{"value": "repeat@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.post(f"/scim/v2/{self.domain.id}/Users", data=user_data_first, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        first_user = User.objects.get(email="repeat@example.com")

        # IdP sends POST request again with same email
        user_data_second = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "repeat@example.com",
            "name": {"givenName": "Second", "familyName": "Time"},
            "emails": [{"value": "repeat@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.post(f"/scim/v2/{self.domain.id}/Users", data=user_data_second, format="json")

        assert response.status_code == status.HTTP_201_CREATED

        # Should NOT create duplicate user
        assert User.objects.filter(email="repeat@example.com").count() == 1

        # User should be updated with new data from second POST
        first_user.refresh_from_db()
        assert first_user.first_name == "Second"
        assert first_user.last_name == "Time"

        # User should have only one membership
        assert OrganizationMembership.objects.filter(user=first_user, organization=self.organization).count() == 1

    def test_get_user(self):
        user = User.objects.create_user(
            email="test@example.com", password=None, first_name="Test", last_name="User", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )
        role = self.organization.roles.create(name="Engineers")

        RoleMembership.objects.create(
            role=role,
            user=user,
            organization_member=OrganizationMembership.objects.get(user=user, organization=self.organization),
        )

        response = self.client.get(f"/scim/v2/{self.domain.id}/Users/{user.id}")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["userName"] == "test@example.com"
        assert data["name"]["givenName"] == "Test"
        assert data["active"] is True
        assert "groups" in data
        assert any(g.get("display") == "Engineers" for g in data["groups"])

    def test_deactivate_user(self):
        user = User.objects.create_user(
            email="deactivate@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"active": False}}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK

        # Verify membership was removed
        assert not OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

        # User still exists
        user.refresh_from_db()
        assert user.is_active is True  # User is still active globally

    def test_delete_user(self):
        user = User.objects.create_user(
            email="delete@example.com", password=None, first_name="Delete", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        response = self.client.delete(f"/scim/v2/{self.domain.id}/Users/{user.id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify membership was removed
        assert not OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

    def test_put_user(self):
        user = User.objects.create_user(
            email="old@example.com", password=None, first_name="Old", last_name="Name", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "put@example.com",
            "name": {"givenName": "Replaced", "familyName": "User"},
            "emails": [{"value": "put@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.put(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=put_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "Replaced"
        assert user.last_name == "User"
        assert user.email == "put@example.com"

    def test_put_user_not_found(self):
        put_data = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "nonexistent@example.com",
            "name": {"givenName": "Should", "familyName": "Fail"},
            "emails": [{"value": "nonexistent@example.com", "primary": True}],
            "active": True,
        }

        fake_user_id = 999999999
        response = self.client.put(f"/scim/v2/{self.domain.id}/Users/{fake_user_id}", data=put_data, format="json")

        assert (
            response.status_code == status.HTTP_404_NOT_FOUND
        ), f"Expected 404, got {response.status_code}: {response.content}"
        assert not User.objects.filter(email="nonexistent@example.com").exists()

    def test_put_user_email_belongs_to_another_user(self):
        # Existing user A in org
        user_a = User.objects.create_user(
            email="alpha@example.com", password=None, first_name="Alpha", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user_a, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        # Existing user B in org
        user_b = User.objects.create_user(
            email="beta@example.com", password=None, first_name="Beta", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user_b, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        # IdP mismatches B and tries to PUT with A email
        put_data_conflict = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "alpha@example.com",
            "name": {"givenName": "Should", "familyName": "Fail"},
            "emails": [{"value": "alpha@example.com", "primary": True}],
            "active": True,
        }

        response = self.client.put(
            f"/scim/v2/{self.domain.id}/Users/{user_b.id}", data=put_data_conflict, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert b"Invalid user data" in response.content

    def test_patch_user_not_found(self):
        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "value": {"name": {"givenName": "Should", "familyName": "Fail"}}}],
        }

        fake_user_id = 999999999
        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{fake_user_id}", data=patch_data, format="json")

        assert (
            response.status_code == status.HTTP_404_NOT_FOUND
        ), f"Expected 404, got {response.status_code}: {response.content}"

    def test_patch_replace_user_without_path(self):
        user = User.objects.create_user(
            email="old@example.com", password=None, first_name="Old", last_name="Name", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "replace",
                    "value": {
                        "name": {"givenName": "New", "familyName": "Name"},
                        "emails": [{"value": "new@example.com", "primary": True}],
                    },
                }
            ],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "New"
        assert user.last_name == "Name"
        assert user.email == "new@example.com"

    def test_patch_replace_user_name_with_simple_path(self):
        user = User.objects.create_user(
            email="pathtest@example.com", password=None, first_name="Path", last_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "name", "value": {"givenName": "NewFirst", "familyName": "NewLast"}}
            ],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "NewFirst"
        assert user.last_name == "NewLast"

    def test_patch_replace_user_emails_with_simple_path(self):
        user = User.objects.create_user(
            email="array@example.com", password=None, first_name="Array", last_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "replace",
                    "path": "emails",
                    "value": [{"value": "newarray@example.com", "primary": True}],
                }
            ],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.email == "newarray@example.com"

    def test_patch_replace_user_given_name_with_dotted_path(self):
        user = User.objects.create_user(
            email="dotpath@example.com", password=None, first_name="Dot", last_name="Path", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "replace", "path": "name.givenName", "value": "UpdatedFirst"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "UpdatedFirst"
        assert user.last_name == "Path"

    def test_patch_replace_user_email_with_filtered_path(self):
        user = User.objects.create_user(
            email="primary@example.com", password=None, first_name="Primary", last_name="Email", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "emails[primary eq true].value", "value": "primaryemail@example.com"}
            ],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.email == "primaryemail@example.com"

    def test_patch_add_user_without_path(self):
        user = User.objects.create_user(
            email="testuser@example.com", password=None, first_name="", last_name="", is_email_verified=True
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {
                    "op": "add",
                    "value": {
                        "name": {"givenName": "New", "familyName": "User"},
                        "emails": [{"value": "newuser@example.com", "primary": True}],
                        "active": True,
                    },
                }
            ],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert user.email == "newuser@example.com"
        assert OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

    def test_patch_add_user_name_with_simple_path(self):
        user = User.objects.create_user(
            email="old@example.com", password=None, first_name="Old", last_name="Name", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "name", "value": {"givenName": "New", "familyName": "Name"}}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "New"
        assert user.last_name == "Name"

    def test_patch_add_active_user_with_simple_path(self):
        user = User.objects.create_user(
            email="reactivate@example.com", password=None, first_name="Test", is_email_verified=True
        )
        assert not OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "active", "value": True}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert OrganizationMembership.objects.filter(user=user, organization=self.organization).exists()

    def test_patch_add_user_given_name_with_dotted_path(self):
        user = User.objects.create_user(
            email="addsubattr@example.com", password=None, first_name="", last_name="Existing", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "name.givenName", "value": "Ada"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "Ada"
        assert user.last_name == "Existing"

    def test_patch_add_user_email_with_filtered_path(self):
        user = User.objects.create_user(
            email="old@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "emails[primary eq true].value", "value": "primary@example.com"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.email == "primary@example.com"

    def test_patch_remove_user_family_name_with_simple_path(self):
        user = User.objects.create_user(
            email="removesimple@example.com",
            password=None,
            first_name="Simple",
            last_name="Fam",
            is_email_verified=True,
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "name.familyName"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "Simple"
        assert user.last_name == ""

    def test_patch_remove_user_family_name_with_dotted_path(self):
        user = User.objects.create_user(
            email="removename@example.com", password=None, first_name="Remove", last_name="Me", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "name.familyName"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_200_OK
        user.refresh_from_db()
        assert user.first_name == "Remove"
        assert user.last_name == ""

    def test_patch_remove_user_emails_should_fail(self):
        user = User.objects.create_user(
            email="email@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "emails"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        user.refresh_from_db()
        assert user.email == "email@example.com"

    def test_patch_remove_user_email_with_filtered_path_should_fail(self):
        user = User.objects.create_user(
            email="primary@example.com", password=None, first_name="Test", is_email_verified=True
        )
        OrganizationMembership.objects.create(
            user=user, organization=self.organization, level=OrganizationMembership.Level.MEMBER
        )

        patch_data = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "remove", "path": "emails[primary eq true].value"}],
        }

        response = self.client.patch(f"/scim/v2/{self.domain.id}/Users/{user.id}", data=patch_data, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        user.refresh_from_db()
        assert user.email == "primary@example.com"
