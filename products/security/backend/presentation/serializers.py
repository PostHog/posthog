"""DRF serializers for security."""

from rest_framework import serializers


class ResolveRequestSerializer(serializers.Serializer):
    query = serializers.CharField(
        max_length=400,
        allow_blank=True,
        trim_whitespace=True,
        help_text="An email address, user UUID or organization UUID.",
    )


class CountAccountsRequestSerializer(serializers.Serializer):
    target_type = serializers.ChoiceField(
        choices=["email", "email_root", "email_domain"], help_text="How target_value matches accounts."
    )
    target_value = serializers.CharField(max_length=320, help_text="The value the hub normalized for this target type.")


class OrgMemberCountRequestSerializer(serializers.Serializer):
    organization_id = serializers.UUIDField(help_text="The organization to count active members of.")


class PosthogMembershipRequestSerializer(serializers.Serializer):
    user_uuid = serializers.UUIDField(required=False, help_text="Check this user's email.")
    organization_id = serializers.UUIDField(required=False, help_text="Check this organization's members.")

    def validate(self, attrs: dict) -> dict:
        if ("user_uuid" in attrs) == ("organization_id" in attrs):
            raise serializers.ValidationError("Send exactly one of user_uuid and organization_id.")
        return attrs


class ResolvedUserSerializer(serializers.Serializer):
    uuid = serializers.CharField(help_text="The user's UUID.")
    email = serializers.CharField(help_text="The user's email address.")
    is_active = serializers.BooleanField(help_text="Whether the account can still sign in.")


class ResolvedOrganizationSerializer(serializers.Serializer):
    id = serializers.CharField(help_text="The organization's UUID.")
    exists = serializers.BooleanField(help_text="Whether the organization exists.")


class ResolveResponseSerializer(serializers.Serializer):
    kind = serializers.CharField(help_text="user, organization or none.")
    user = ResolvedUserSerializer(allow_null=True, help_text="The matched user, when the query named one.")
    organization_ids = serializers.ListField(
        child=serializers.CharField(), help_text="The organizations the match belongs to."
    )
    organization = ResolvedOrganizationSerializer(
        allow_null=True, help_text="The matched organization, when the query named one."
    )


class CountResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Active accounts the rule would hit.")
    capped = serializers.BooleanField(help_text="Whether counting stopped at the cap.")


class OrgMemberCountResponseSerializer(serializers.Serializer):
    exists = serializers.BooleanField(help_text="Whether the organization exists.")
    active_members = serializers.IntegerField(help_text="Active members of the organization.")
    capped = serializers.BooleanField(help_text="Whether counting stopped at the cap.")


class PosthogMembershipResponseSerializer(serializers.Serializer):
    has_posthog_account = serializers.BooleanField(help_text="Whether the target holds a posthog.com account.")
