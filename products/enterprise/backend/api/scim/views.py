from typing import cast

from django.db.models import QuerySet

from django_scim import constants
from django_scim.filters import GroupFilterQuery, UserFilterQuery
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from posthog.exceptions_capture import capture_exception
from posthog.models import User
from posthog.models.organization_domain import OrganizationDomain

from products.enterprise.backend.api.scim.auth import SCIMBearerTokenAuthentication
from products.enterprise.backend.api.scim.group import PostHogSCIMGroup
from products.enterprise.backend.api.scim.user import PostHogSCIMUser
from products.enterprise.backend.models.rbac.role import Role

SCIM_USER_ATTR_MAP = {
    ("userName", None, None): "email",
    ("emails", "value", None): "email",
    ("name", "familyName", None): "last_name",
    ("familyName", None, None): "last_name",
    ("name", "givenName", None): "first_name",
    ("givenName", None, None): "first_name",
    ("active", None, None): "is_active",
}

SCIM_GROUP_ATTR_MAP = {
    ("displayName", None, None): "name",
}


class PostHogUserFilterQuery(UserFilterQuery):
    attr_map = SCIM_USER_ATTR_MAP

    @classmethod
    def search(cls, filter_query: str, request: Request) -> QuerySet[User]:
        raw_queryset = super().search(filter_query, request)
        # Filter results to only include users from the specified organization
        org_domain = cast(OrganizationDomain, request.auth)
        user_ids = [user.id for user in raw_queryset]
        return User.objects.filter(
            id__in=user_ids,
            organization_membership__organization=org_domain.organization,
        )


class PostHogGroupFilterQuery(GroupFilterQuery):
    attr_map = SCIM_GROUP_ATTR_MAP

    @classmethod
    def search(cls, filter_query: str, request: Request) -> QuerySet[Role]:
        raw_queryset = super().search(filter_query, request)
        # Filter results to only include roles from the specified organization
        org_domain = cast(OrganizationDomain, request.auth)
        role_ids = [role.id for role in raw_queryset]
        return Role.objects.filter(
            id__in=role_ids,
            organization=org_domain.organization,
        )


class SCIMUsersView(APIView):
    authentication_classes = [SCIMBearerTokenAuthentication]

    def get(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        filter_param = request.query_params.get("filter")

        if filter_param:
            try:
                queryset = PostHogUserFilterQuery.search(filter_param, request)
                users = [PostHogSCIMUser(u, organization_domain) for u in queryset]
            except Exception as e:
                capture_exception(
                    e,
                    additional_properties={
                        "scim_operation": "filter_users",
                        "filter": filter_param,
                        "domain_id": domain_id,
                        "organization_id": organization_domain.organization.id,
                    },
                )
                users = []
        else:
            users = PostHogSCIMUser.get_for_organization(organization_domain)

        return Response(
            {
                "schemas": [constants.SchemaURI.LIST_RESPONSE],
                "totalResults": len(users),
                "startIndex": 1,
                "itemsPerPage": len(users),
                "Resources": [user.to_dict() for user in users],
            }
        )

    def post(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        try:
            scim_user = PostHogSCIMUser.from_dict(request.data, organization_domain)
            return Response(scim_user.to_dict(), status=status.HTTP_201_CREATED)
        except ValueError as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "create_user",
                    "domain_id": domain_id,
                    "organization_id": organization_domain.organization.id,
                    "request_data": request.data,
                },
            )
            return Response({"detail": "Invalid user data"}, status=status.HTTP_400_BAD_REQUEST)


class SCIMUserDetailView(APIView):
    authentication_classes = [SCIMBearerTokenAuthentication]

    def get_object(self, user_id: int) -> PostHogSCIMUser:
        organization_domain = cast(OrganizationDomain, self.request.auth)
        user = User.objects.filter(id=user_id).first()
        if not user:
            raise User.DoesNotExist()
        return PostHogSCIMUser(user, organization_domain)

    def handle_exception(self, exc):
        if isinstance(exc, User.DoesNotExist):
            return Response({"detail": "User not found"}, status=status.HTTP_404_NOT_FOUND)
        return super().handle_exception(exc)

    def get(self, request: Request, domain_id: str, user_id: int) -> Response:
        scim_user = self.get_object(user_id)
        return Response(scim_user.to_dict())

    def put(self, request: Request, domain_id: str, user_id: int) -> Response:
        scim_user = self.get_object(user_id)
        try:
            scim_user.put(request.data)
            return Response(scim_user.to_dict())
        except ValueError as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "replace_user",
                    "user_id": user_id,
                    "domain_id": domain_id,
                    "organization_id": cast(OrganizationDomain, request.auth).organization.id,
                    "request_data": request.data,
                },
            )
            return Response({"detail": "Invalid user data"}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request: Request, domain_id: str, user_id: int) -> Response:
        scim_user = self.get_object(user_id)
        try:
            operations = request.data.get("Operations", [])
            scim_user.handle_operations(operations)
            return Response(scim_user.to_dict())
        except Exception as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "update_user",
                    "user_id": user_id,
                    "domain_id": domain_id,
                    "organization_id": cast(OrganizationDomain, request.auth).organization.id,
                    "request_data": request.data,
                },
            )
            return Response({"detail": "Failed to update user"}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request: Request, domain_id: str, user_id: int) -> Response:
        scim_user = self.get_object(user_id)
        scim_user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SCIMGroupsView(APIView):
    authentication_classes = [SCIMBearerTokenAuthentication]

    def get(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        filter_param = request.query_params.get("filter")

        if filter_param:
            try:
                queryset = PostHogGroupFilterQuery.search(filter_param, request)
                groups = [PostHogSCIMGroup(role, organization_domain) for role in queryset]
            except Exception as e:
                capture_exception(
                    e,
                    additional_properties={
                        "scim_operation": "filter_groups",
                        "filter": filter_param,
                        "domain_id": domain_id,
                        "organization_id": organization_domain.organization.id,
                    },
                )
                groups = []
        else:
            groups = PostHogSCIMGroup.get_for_organization(organization_domain)

        return Response(
            {
                "schemas": [constants.SchemaURI.LIST_RESPONSE],
                "totalResults": len(groups),
                "startIndex": 1,
                "itemsPerPage": len(groups),
                "Resources": [group.to_dict() for group in groups],
            }
        )

    def post(self, request: Request, domain_id: str) -> Response:
        organization_domain = cast(OrganizationDomain, request.auth)
        try:
            scim_group = PostHogSCIMGroup.from_dict(request.data, organization_domain)
            return Response(scim_group.to_dict(), status=status.HTTP_201_CREATED)
        except ValueError as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "create_group",
                    "domain_id": domain_id,
                    "organization_id": organization_domain.organization.id,
                    "request_data": request.data,
                },
            )
            return Response({"detail": "Invalid group data"}, status=status.HTTP_400_BAD_REQUEST)


class SCIMGroupDetailView(APIView):
    authentication_classes = [SCIMBearerTokenAuthentication]

    def get_object(self, group_id: str) -> PostHogSCIMGroup:
        organization_domain = cast(OrganizationDomain, self.request.auth)
        role = Role.objects.filter(id=group_id, organization=organization_domain.organization).first()
        if not role:
            raise Role.DoesNotExist()
        return PostHogSCIMGroup(role, organization_domain)

    def handle_exception(self, exc):
        if isinstance(exc, Role.DoesNotExist):
            return Response({"detail": "Group not found"}, status=status.HTTP_404_NOT_FOUND)
        return super().handle_exception(exc)

    def get(self, request: Request, domain_id: str, group_id: str) -> Response:
        scim_group = self.get_object(group_id)
        return Response(scim_group.to_dict())

    def put(self, request: Request, domain_id: str, group_id: str) -> Response:
        scim_group = self.get_object(group_id)
        try:
            scim_group.put(request.data)
            return Response(scim_group.to_dict())
        except ValueError as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "replace_group",
                    "group_id": group_id,
                    "domain_id": domain_id,
                    "organization_id": cast(OrganizationDomain, request.auth).organization.id,
                    "request_data": request.data,
                },
            )
            return Response({"detail": "Invalid group data"}, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request: Request, domain_id: str, group_id: str) -> Response:
        scim_group = self.get_object(group_id)
        try:
            operations = request.data.get("Operations", [])
            scim_group.handle_operations(operations)
            return Response(scim_group.to_dict())
        except Exception as e:
            capture_exception(
                e,
                additional_properties={
                    "scim_operation": "update_group",
                    "group_id": group_id,
                    "domain_id": domain_id,
                    "organization_id": cast(OrganizationDomain, request.auth).organization.id,
                    "request_data": request.data,
                },
            )
            return Response({"detail": "Failed to update group"}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request: Request, domain_id: str, group_id: str) -> Response:
        scim_group = self.get_object(group_id)
        scim_group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SCIMServiceProviderConfigView(APIView):
    authentication_classes = [SCIMBearerTokenAuthentication]

    def get(self, request: Request, domain_id: str) -> Response:
        return Response(
            {
                "schemas": [constants.SchemaURI.SERVICE_PROVIDER_CONFIG],
                "documentationUri": "https://posthog.com/docs/scim",
                "patch": {"supported": True},
                "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
                "filter": {"supported": True, "maxResults": 200},
                "changePassword": {"supported": False},
                "sort": {"supported": False},
                "etag": {"supported": False},
                "authenticationSchemes": [
                    {
                        "type": "oauthbearertoken",
                        "name": "OAuth Bearer Token",
                        "description": "Authentication scheme using the OAuth Bearer Token Standard",
                        "specUri": "https://www.rfc-editor.org/rfc/rfc6750.txt",
                        "documentationUri": "https://posthog.com/docs/settings/scim",
                    }
                ],
            }
        )


class SCIMResourceTypesView(APIView):
    authentication_classes = [SCIMBearerTokenAuthentication]

    def get(self, request: Request, domain_id: str) -> Response:
        return Response(
            {
                "schemas": [constants.SchemaURI.LIST_RESPONSE],
                "totalResults": 2,
                "Resources": [
                    PostHogSCIMUser.resource_type_dict(request),
                    PostHogSCIMGroup.resource_type_dict(request),
                ],
            }
        )


class SCIMSchemasView(APIView):
    authentication_classes = [SCIMBearerTokenAuthentication]

    def get(self, request: Request, domain_id: str) -> Response:
        return Response(
            {
                "schemas": [constants.SchemaURI.LIST_RESPONSE],
                "totalResults": 2,
                "Resources": [
                    {
                        "id": constants.SchemaURI.USER,
                        "name": "User",
                        "description": "User Account",
                    },
                    {
                        "id": constants.SchemaURI.GROUP,
                        "name": "Group",
                        "description": "Group",
                    },
                ],
            }
        )
