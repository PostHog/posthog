from django.utils import timezone

from loginas.utils import is_impersonated_session
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin
from posthog.models import PropertyDefinition
from posthog.models.activity_logging.activity_log import Detail, dict_changes_between, log_activity

from products.enterprise.backend.models.property_definition import EnterprisePropertyDefinition


class EnterprisePropertyDefinitionSerializer(TaggedItemSerializerMixin, serializers.ModelSerializer):
    updated_by = UserBasicSerializer(read_only=True)
    verified_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = EnterprisePropertyDefinition
        fields = (
            "id",
            "name",
            "description",
            "tags",
            "is_numerical",
            "updated_at",
            "updated_by",
            "is_seen_on_filtered_events",
            "property_type",
            "verified",
            "verified_at",
            "verified_by",
            "hidden",
        )
        read_only_fields = [
            "id",
            "name",
            "is_numerical",
            "is_seen_on_filtered_events",
            "verified_at",
            "verified_by",
        ]

    def validate(self, data):
        validated_data = super().validate(data)

        if "hidden" in validated_data and "verified" in validated_data:
            if validated_data["hidden"] and validated_data["verified"]:
                raise serializers.ValidationError("A property cannot be both hidden and verified")

        # If setting hidden=True, ensure verified becomes false
        if validated_data.get("hidden", False):
            validated_data["verified"] = False
        # If setting verified=True, ensure hidden becomes false
        elif validated_data.get("verified", False):
            validated_data["hidden"] = False

        return validated_data

    def update(self, property_definition: EnterprisePropertyDefinition, validated_data: dict):
        # If setting hidden=True, ensure verified becomes false
        if validated_data.get("hidden", False):
            validated_data["verified"] = False
            validated_data["verified_by"] = None
            validated_data["verified_at"] = None
        # If setting verified=True, ensure hidden becomes false
        elif validated_data.get("verified", False):
            validated_data["hidden"] = False

        validated_data["updated_by"] = self.context["request"].user
        if "property_type" in validated_data:
            if validated_data["property_type"] == "Numeric":
                validated_data["is_numerical"] = True
            else:
                validated_data["is_numerical"] = False

        if "verified" in validated_data:
            if validated_data["verified"] and not property_definition.verified:
                # Verify property only if previously unverified
                validated_data["verified_by"] = self.context["request"].user
                validated_data["verified_at"] = timezone.now()
                validated_data["verified"] = True
            elif not validated_data["verified"]:
                # Unverifying property nullifies verified properties
                validated_data["verified_by"] = None
                validated_data["verified_at"] = None
                validated_data["verified"] = False
            else:
                # Attempting to re-verify an already verified property, invalid action. Ignore attribute.
                validated_data.pop("verified")

        before_state = {
            k: property_definition.__dict__[k] for k in validated_data.keys() if k in property_definition.__dict__
        }
        # KLUDGE: if we get a None value for tags, and we're not adding any
        # then we get an activity log that we went from null to the empty array ¯\_(ツ)_/¯
        if "tags" not in before_state or before_state["tags"] is None:
            before_state["tags"] = []

        changes = dict_changes_between("PropertyDefinition", before_state, validated_data, True)

        log_activity(
            organization_id=None,
            team_id=self.context["team_id"],
            user=self.context["request"].user,
            was_impersonated=is_impersonated_session(self.context["request"]),
            item_id=str(property_definition.id),
            scope="PropertyDefinition",
            activity="changed",
            detail=Detail(
                name=str(property_definition.name),
                type=PropertyDefinition.Type(property_definition.type).label,
                changes=changes,
            ),
        )

        return super().update(property_definition, validated_data)
