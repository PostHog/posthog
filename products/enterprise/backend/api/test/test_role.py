from django.db import IntegrityError

from rest_framework import status

from posthog.models.organization import Organization, OrganizationMembership

from products.enterprise.backend.api.test.base import APILicensedTest
from products.enterprise.backend.models.rbac.role import Role


class TestRoleAPI(APILicensedTest):
    def test_only_organization_admins_and_higher_can_create(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_create_res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product",
            },
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_create_res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product 2",
            },
        )
        self.assertEqual(admin_create_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Role.objects.all().count(), 1)
        self.assertEqual(Role.objects.first().name, "Product")  # type: ignore
        self.assertEqual(member_create_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_organization_admins_and_higher_can_update(self):
        existing_eng_role = Role.objects.create(
            name="Engineering",
            organization=self.organization,
            created_by=self.user,
        )
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        admin_update_res = self.client.patch(
            f"/api/organizations/@current/roles/{existing_eng_role.id}",
            {"name": "on call support"},
        )

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        member_update_res = self.client.patch(
            f"/api/organizations/@current/roles/{existing_eng_role.id}",
            {"name": "member eng"},
        )

        self.assertEqual(admin_update_res.status_code, status.HTTP_200_OK)
        self.assertEqual(member_update_res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(Role.objects.all().count(), 1)
        self.assertEqual(Role.objects.first().name, "on call support")  # type: ignore

    def test_cannot_duplicate_role_name(self):
        Role.objects.create(name="Marketing", organization=self.organization)
        count = Role.objects.count()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        res = self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "marketing",
            },
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": "There is already a role with this name.",
                "attr": "name",
            },
        )
        self.assertEqual(Role.objects.count(), count)
        other_org = Organization.objects.create(name="other org")
        Role.objects.create(name="Marketing", organization=other_org)
        self.assertEqual(Role.objects.count(), 2)
        self.assertEqual(Role.objects.filter(organization=other_org).exists(), True)
        with self.assertRaises(IntegrityError):
            Role.objects.create(name="Marketing", organization=self.organization)

    def test_returns_correct_results_by_organization(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Product",
            },
        )
        self.client.post(
            "/api/organizations/@current/roles",
            {
                "name": "Customer Success",
            },
        )
        other_org = Organization.objects.create(name="other org")
        Role.objects.create(name="Product", organization=other_org)
        self.assertEqual(Role.objects.count(), 3)
        res = self.client.get("/api/organizations/@current/roles")
        results = res.json()
        self.assertEqual(results["count"], 2)
        self.assertNotContains(res, str(other_org.id))
