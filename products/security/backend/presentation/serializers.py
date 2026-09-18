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
