from typing import Any

from django.db import transaction

from croniter import croniter  # type: ignore[import-untyped,unused-ignore]
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer

from products.approvals.backend.mixins import ApprovalHandlingMixin
from products.approvals.backend.models import ChangeRequest, ChangeRequestState
from products.approvals.backend.scheduled_changes import gate_scheduled_change
from products.feature_flags.backend.api.feature_flag import CanEditFeatureFlag
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.scheduled_change import ScheduledChange


def _gate_scheduled_change_at_creation(
    model_name: str | None,
    record_id: Any,
    team_id: int,
    payload: dict,
    user: Any,
) -> ChangeRequest | None:
    """Create a pending ChangeRequest if a scheduled change targets a policy-gated field.

    Returns the CR to bind to the new ScheduledChange, or None when no policy applies (the
    common case). Only feature-flag schedules are gated; a missing target flag is left to the
    existing edit-permission check, which already validates the flag exists.
    """
    if model_name != ScheduledChange.AllowedModels.FEATURE_FLAG or not record_id:
        return None

    flag = FeatureFlag.objects.filter(id=record_id, team_id=team_id).first()
    if flag is None:
        return None

    return gate_scheduled_change(flag, payload, user)


class ScheduledChangeSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    failure_reason = serializers.SerializerMethodField()

    record_id = serializers.CharField(
        max_length=200,
        help_text="The ID of the record to modify (e.g. the feature flag ID).",
    )
    model_name = serializers.ChoiceField(
        choices=ScheduledChange.AllowedModels.choices,
        help_text='The type of record to modify. Currently only "FeatureFlag" is supported.',
    )
    payload = serializers.JSONField(
        help_text=(
            "The change to apply. Must include an 'operation' key and a 'value' key. "
            "Supported operations: 'update_status' (value: true/false to enable/disable the flag), "
            "'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), "
            "'update_variants' (value: object with 'variants' and 'payloads' keys)."
        ),
    )
    scheduled_at = serializers.DateTimeField(
        help_text="ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z').",
    )
    is_recurring = serializers.BooleanField(
        default=False,
        help_text="Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules.",
    )
    recurrence_interval = serializers.ChoiceField(
        choices=ScheduledChange.RecurrenceInterval.choices,
        required=False,
        allow_null=True,
        help_text="How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.",
    )
    end_date = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Optional ISO 8601 datetime after which a recurring schedule stops executing.",
    )

    class Meta:
        model = ScheduledChange
        fields = [
            "id",
            "team_id",
            "record_id",
            "model_name",
            "payload",
            "scheduled_at",
            "executed_at",
            "failure_reason",
            "created_at",
            "created_by",
            "updated_at",
            "is_recurring",
            "recurrence_interval",
            "cron_expression",
            "last_executed_at",
            "end_date",
            "timezone",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "updated_at",
            "last_executed_at",
            "executed_at",
            "timezone",
        ]

    def get_failure_reason(self, obj: ScheduledChange) -> str | None:
        """Return the safely formatted failure reason instead of raw data."""
        if not obj.failure_reason:
            return None
        return obj.formatted_failure_reason

    def validate(self, data: dict) -> dict:
        instance = getattr(self, "instance", None)

        # Prevent changing the target record on updates (defense in depth against cross-tenant manipulation)
        if instance:
            if "record_id" in data and str(data["record_id"]) != str(instance.record_id):
                raise serializers.ValidationError(
                    {"record_id": "Cannot change the target record of an existing scheduled change."}
                )
            if "model_name" in data and data["model_name"] != instance.model_name:
                raise serializers.ValidationError(
                    {"model_name": "Cannot change the model type of an existing scheduled change."}
                )

            # A completed one-time schedule is immutable. Recurring schedules legitimately carry
            # executed_at=NULL while active, so this guard only trips for one-time completions.
            if instance.executed_at is not None and not instance.is_recurring:
                raise serializers.ValidationError("Cannot modify a scheduled change that has already executed.")

            self._reject_timing_change_on_gated_schedule(instance, data)

        # For updates, merge with existing instance values
        is_recurring = data.get("is_recurring", getattr(instance, "is_recurring", False) if instance else False)
        recurrence_interval = data.get(
            "recurrence_interval", getattr(instance, "recurrence_interval", None) if instance else None
        )
        cron_expression = data.get("cron_expression", getattr(instance, "cron_expression", None) if instance else None)
        payload = data.get("payload", getattr(instance, "payload", {}) if instance else {})

        # cron_expression and recurrence_interval are mutually exclusive
        if cron_expression and recurrence_interval:
            raise serializers.ValidationError(
                {"cron_expression": "Cannot set both cron_expression and recurrence_interval. Use one or the other."}
            )

        # Validate cron expression syntax (only standard 5-field expressions are allowed)
        if cron_expression:
            parts = cron_expression.strip().split()
            if len(parts) != 5:
                raise serializers.ValidationError(
                    {
                        "cron_expression": "Only standard 5-field cron expressions are supported "
                        "(minute hour day month weekday). Example: '0 9 * * 1-5'."
                    }
                )
            if not croniter.is_valid(cron_expression):
                raise serializers.ValidationError(
                    {
                        "cron_expression": "Invalid cron expression. Use standard 5-field cron syntax (e.g., '0 9 * * 1-5')."
                    }
                )

        if is_recurring:
            if not recurrence_interval and not cron_expression:
                raise serializers.ValidationError(
                    {
                        "recurrence_interval": "Either recurrence_interval or cron_expression is required when is_recurring is true."
                    }
                )
            # Validate recurrence_interval is a valid choice (when using interval mode)
            if recurrence_interval:
                valid_intervals = [choice[0] for choice in ScheduledChange.RecurrenceInterval.choices]
                if recurrence_interval not in valid_intervals:
                    raise serializers.ValidationError(
                        {"recurrence_interval": f"Must be one of: {', '.join(valid_intervals)}"}
                    )
            # Recurring add_release_condition is not supported because it appends
            # condition groups on each run, creating duplicates.
            if payload.get("operation") == ScheduledChange.OperationType.ADD_RELEASE_CONDITION:
                raise serializers.ValidationError(
                    {
                        "payload": "Recurring schedules are not supported for add_release_condition "
                        "because it appends conditions on each run, creating duplicates."
                    }
                )
        # For new schedules (create), if is_recurring is false, recurrence config must be null.
        # We only preserve recurrence config when is_recurring=false for UPDATES (pausing existing schedules).
        if not instance and not is_recurring:
            if recurrence_interval:
                raise serializers.ValidationError(
                    {
                        "recurrence_interval": "Cannot set recurrence_interval when is_recurring is false for new schedules."
                    }
                )
            if cron_expression:
                raise serializers.ValidationError(
                    {"cron_expression": "Cannot set cron_expression when is_recurring is false for new schedules."}
                )

        # Validate end_date is after scheduled_at
        end_date = data.get("end_date", getattr(instance, "end_date", None) if instance else None)
        scheduled_at = data.get("scheduled_at", getattr(instance, "scheduled_at", None) if instance else None)
        if end_date and scheduled_at and end_date <= scheduled_at:
            raise serializers.ValidationError({"end_date": "End date must be after the scheduled start date."})

        return data

    # Fields that determine *when* a scheduled change fires. Re-gating (see update()) only covers
    # *what* it applies, so these are locked once a schedule carries a live approval.
    TIMING_FIELDS = ("scheduled_at", "cron_expression", "recurrence_interval", "end_date", "is_recurring")

    def _reject_timing_change_on_gated_schedule(self, instance: ScheduledChange, data: dict) -> None:
        """Block retiming a schedule whose bound ChangeRequest is still pending or approved.

        An approver signs off on a change firing within a specific window. Re-gating only reacts to
        payload edits, so without this an editor could wait for a future schedule to be approved and
        then PATCH scheduled_at (or the recurrence config) to fire the approved change at a moment the
        approval never covered — e.g. move it earlier to apply immediately. Deleting and recreating
        the schedule re-gates from scratch, so this only forbids retiming a change mid-approval.
        """
        change_request = instance.change_request
        if change_request is None or change_request.state not in (
            ChangeRequestState.PENDING,
            ChangeRequestState.APPROVED,
        ):
            return
        changed = [field for field in self.TIMING_FIELDS if field in data and data[field] != getattr(instance, field)]
        if changed:
            raise serializers.ValidationError(
                {
                    changed[0]: (
                        "Cannot change the timing of a scheduled change while its approval request is "
                        "pending or approved. Delete this schedule and create a new one to reschedule."
                    )
                }
            )

    def _check_target_edit_permission(self, model_name: str | None, record_id: Any, team_id: int) -> FeatureFlag | None:
        """Enforce edit permission on the target record and return the resolved flag (None if not a flag)."""
        if model_name != ScheduledChange.AllowedModels.FEATURE_FLAG or not record_id:
            return None

        try:
            feature_flag = FeatureFlag.objects.get(id=record_id, team_id=team_id)
        except (FeatureFlag.DoesNotExist, ValueError):
            # ValueError: non-numeric record_id (record_id is a free-form CharField) — treat as not found.
            raise serializers.ValidationError("Feature flag not found")

        request = self.context["request"]
        if not CanEditFeatureFlag().has_object_permission(request, None, feature_flag):
            raise serializers.ValidationError("You don't have edit permissions for this feature flag")

        return feature_flag

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> ScheduledChange:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]

        feature_flag = self._check_target_edit_permission(
            validated_data.get("model_name"), validated_data.get("record_id"), validated_data["team_id"]
        )
        # Store the canonical flag id. record_id is a free-form CharField, so "000123"/" 123" resolve to the
        # same flag here but would dodge the str-equality access filter in the viewset if persisted verbatim.
        if feature_flag is not None:
            validated_data["record_id"] = str(feature_flag.id)

        # Capture the project's timezone at creation time so cron recurrence resolves
        # wall-clock fields in that timezone, independent of later team.timezone changes.
        team = self.context["get_team"]()
        validated_data["timezone"] = team.timezone

        # Gate at scheduling time: if the change would flip a policy-gated field, create a pending
        # ChangeRequest now and bind it so the applier only applies once approved (see
        # process_scheduled_changes). NULL change_request means no policy applies — apply as before.
        #
        # Create the CR and the ScheduledChange row in one transaction: the applier defers a bound CR
        # to fire time only while its schedule row exists (approve() keys off scheduled_changes.exists()).
        # If the row insert failed after the CR was created, the CR would be orphaned and a later
        # approval would auto-apply it immediately, bypassing the schedule.
        with transaction.atomic():
            validated_data["change_request"] = _gate_scheduled_change_at_creation(
                validated_data.get("model_name"),
                validated_data.get("record_id"),
                validated_data["team_id"],
                validated_data.get("payload", {}),
                validated_data["created_by"],
            )

            return super().create(validated_data)

    def update(self, instance: ScheduledChange, validated_data: dict) -> ScheduledChange:
        # Enforce the same edit-permission check on updates. record_id/model_name can't be changed
        # (blocked in validate()), so the instance's existing target is authoritative.
        feature_flag = self._check_target_edit_permission(instance.model_name, instance.record_id, instance.team_id)
        # Canonicalize any legacy non-canonical record_id so the access filter keeps matching it.
        if feature_flag is not None:
            instance.record_id = str(feature_flag.id)

        # Re-gate whenever the payload changes: create() only gates the payload the row is born with,
        # so without this an editor could create an ungated schedule and then PATCH its payload to a
        # policy-gated change, which the applier would dispatch with change_request=None (ungated).
        if feature_flag is None or "payload" not in validated_data:
            return super().update(instance, validated_data)

        # Re-gate (which can mint a fresh CR) and bind it in one transaction, mirroring create(): if
        # the row update fails after the new CR is created, the CR — and the old-CR expiry — roll
        # back together, so a failed update can't orphan a pending CR that approve() then auto-applies
        # immediately, bypassing the schedule.
        with transaction.atomic():
            validated_data["change_request"] = self._regate_on_payload_change(
                instance, feature_flag, validated_data["payload"]
            )
            return super().update(instance, validated_data)

    def _regate_on_payload_change(
        self, instance: ScheduledChange, feature_flag: FeatureFlag, new_payload: dict
    ) -> ChangeRequest | None:
        """Re-evaluate the approval gate against a changed payload and return the CR to bind.

        Expires any previously bound pending CR that the new payload no longer needs, so a stale
        request can't be approved into applying a change the row no longer carries.

        Gate as the user making the edit, not the original creator: a creator with approval-bypass
        would otherwise let any editor PATCH in a gated payload that stays unbound and applies
        unapproved.
        """
        existing = instance.change_request
        # Pass the schedule's own bound CR so re-gating an unchanged action rediscovers and reuses it
        # instead of failing closed on its own pending binding.
        new_change_request = gate_scheduled_change(
            feature_flag, new_payload, self.context["request"].user, current_change_request=existing
        )
        if (
            existing is not None
            and existing.state == ChangeRequestState.PENDING
            and (new_change_request is None or new_change_request.id != existing.id)
        ):
            existing.state = ChangeRequestState.EXPIRED
            existing.save(update_fields=["state"])
        return new_change_request


@extend_schema(extensions={"x-product": "feature_flags"})
class ScheduledChangeViewSet(ApprovalHandlingMixin, TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    Create, read, update and delete scheduled changes.
    """

    scope_object = "feature_flag"
    serializer_class = ScheduledChangeSerializer
    queryset = ScheduledChange.objects.all()

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "model_name",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description='Filter by model type. Use "FeatureFlag" to see feature flag schedules.',
            ),
            OpenApiParameter(
                "record_id",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by the ID of a specific feature flag.",
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def safely_get_queryset(self, queryset):
        model_name = self.request.query_params.get("model_name")
        record_id = self.request.query_params.get("record_id")

        if model_name is not None:
            queryset = queryset.filter(model_name=model_name)
        if record_id is not None:
            queryset = queryset.filter(record_id=record_id)

        # The target flag lives in record_id, so per-flag access controls don't apply to
        # ScheduledChange rows automatically. Hide schedules for flags the user is denied,
        # so reads match feature-flag visibility (list/retrieve; retrieve then 404s).
        denied_flag_ids = self._inaccessible_feature_flag_ids()
        if denied_flag_ids:
            queryset = queryset.exclude(
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG, record_id__in=denied_flag_ids
            )

        return queryset

    def perform_destroy(self, instance: ScheduledChange) -> None:
        # Deleting a schedule cancels a pending flag change, so require edit access on the
        # target flag — mirroring the create/update checks enforced by the serializer.
        self._assert_can_edit_target_flag(instance)
        change_request = instance.change_request
        with transaction.atomic():
            super().perform_destroy(instance)
            # Deleting the schedule cancels the change it carried, so expire the bound (non-terminal)
            # ChangeRequest unless another schedule still shares it. Otherwise a pending CR would
            # outlive its schedule and auto-apply on quorum: ChangeRequestService.approve() only
            # defers application while a bound schedule row exists (scheduled_changes.exists()), so
            # once the row is gone the deferral is skipped and the flag change fires immediately on
            # approval — bypassing the scheduled timing the approval was granted for.
            if (
                change_request is not None
                and change_request.state in (ChangeRequestState.PENDING, ChangeRequestState.APPROVED)
                and not change_request.scheduled_changes.exists()
            ):
                change_request.state = ChangeRequestState.EXPIRED
                change_request.save(update_fields=["state"])

    def _inaccessible_feature_flag_ids(self) -> set[str]:
        """Return record_ids of feature flags in this project the user may not access."""
        if not self.user_access_control.access_controls_supported:
            return set()
        flags = FeatureFlag.objects.filter(team__project_id=self.project_id)
        accessible = self.user_access_control.filter_queryset_by_access_level(flags, include_all_if_admin=True)
        denied = flags.exclude(pk__in=accessible.values("pk"))
        return {str(pk) for pk in denied.values_list("id", flat=True)}

    def _assert_can_edit_target_flag(self, instance: ScheduledChange) -> None:
        if instance.model_name != ScheduledChange.AllowedModels.FEATURE_FLAG or not instance.record_id:
            return
        try:
            feature_flag = FeatureFlag.objects.get(id=instance.record_id, team_id=instance.team_id)
        except (FeatureFlag.DoesNotExist, ValueError):
            # Orphaned schedule (flag deleted / non-numeric record_id): allow team-scoped cleanup.
            return
        # Reuse the viewset's access-control instance (warmed by safely_get_queryset) instead of
        # CanEditFeatureFlag, which would build a fresh UserAccessControl with cold caches per delete.
        if not self.user_access_control.check_access_level_for_object(feature_flag, "editor"):
            raise PermissionDenied("You don't have edit permissions for this feature flag")
