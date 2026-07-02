"""Create/update/delete orchestration for endpoints.

``EndpointCrudService`` owns the write-path business rules: version creation on
query change, materialization transfer between versions, tag application, and
activity logging. The viewset only parses/validates the request and serializes
the result.
"""

import dataclasses
from typing import Union, cast

from django.db import transaction

import structlog
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.request import Request

from posthog.schema import EndpointRequest, HogQLQuery

from posthog.api.tagged_item import cleanup_orphan_tags, set_tags_on_object
from posthog.clickhouse.query_tagging import Product
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, changes_between, log_activity
from posthog.types import InsightQueryNode

from products.data_modeling.backend.facade.api import delete_node_from_dag
from products.data_warehouse.backend.facade.api import trigger_saved_query_schedule
from products.endpoints.backend.constants import DEFAULT_DATA_FRESHNESS_SECONDS
from products.endpoints.backend.logic.activity import EndpointContext
from products.endpoints.backend.logic.materialization import EndpointMaterializationService
from products.endpoints.backend.logic.validation import validate_bucket_overrides
from products.endpoints.backend.models import Endpoint, EndpointVersion
from products.endpoints.backend.rate_limit import clear_endpoint_materialization_cache

logger = structlog.get_logger(__name__)


def apply_tags(endpoint: Endpoint, tags: list[str] | None) -> None:
    """Replace the endpoint's tags. No-op when tags is None (field omitted)."""
    if tags is None:
        return
    # `prefetched_tags` is a dynamic attribute populated by the TaggedItem prefetch / set_tags_on_object;
    # it's not declared on the Endpoint model.
    endpoint.prefetched_tags = set_tags_on_object(tags, endpoint)  # type: ignore[attr-defined]
    cleanup_orphan_tags(endpoint.team_id)


@dataclasses.dataclass(frozen=True)
class EndpointUpdateResult:
    """Outcome of an update, with everything the viewset needs to build the response."""

    endpoint: Endpoint
    target_version: EndpointVersion
    version_targeted: bool
    materialization_error: str | None = None


class EndpointCrudService:
    """Write-path orchestration for endpoints."""

    def __init__(self, team: Team, request: Request):
        self.team = team
        self.request = request
        self.user = cast(User, request.user)
        self.materialization = EndpointMaterializationService(team, request)

    def _log_activity(self, *, item_id: str, scope: str, activity: str, detail: Detail) -> None:
        log_activity(
            organization_id=self.team.organization_id,
            team_id=self.team.pk,
            user=self.user,
            was_impersonated=is_impersonated(self.request),
            item_id=item_id,
            scope=scope,
            activity=activity,
            detail=detail,
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, data: EndpointRequest) -> Endpoint:
        """Create an endpoint with its initial version. Assumes the payload is validated."""
        if Endpoint.objects.filter(team=self.team, name=data.name, deleted=False).exists():
            raise ValidationError({"name": "An endpoint with this name already exists for this team."})

        try:
            query_dict = cast(Union[HogQLQuery, InsightQueryNode], data.query).model_dump()

            # Column extraction hits ClickHouse — do it outside the transaction.
            try:
                columns: list[dict] | None = EndpointVersion.extract_columns(query_dict, team_id=self.team.pk)
            except Exception as e:
                capture_exception(
                    e,
                    {"product": Product.ENDPOINTS, "team_id": self.team.pk, "endpoint_name": data.name},
                )
                columns = None

            # The endpoint and its initial version must exist together — a version-less
            # endpoint can't run and would squat on the name.
            with transaction.atomic():
                endpoint = Endpoint.objects.create(
                    team=self.team,
                    created_by=self.user,
                    name=cast(str, data.name),  # verified in validate_endpoint_request
                    is_active=data.is_active if data.is_active is not None else True,
                    current_version=1,
                    derived_from_insight=data.derived_from_insight,
                )
                EndpointVersion.objects.create(
                    endpoint=endpoint,
                    team=self.team,
                    version=1,
                    query=query_dict,
                    description=data.description or "",
                    data_freshness_seconds=(
                        data.data_freshness_seconds
                        if data.data_freshness_seconds is not None
                        else DEFAULT_DATA_FRESHNESS_SECONDS
                    ),
                    created_by=self.user,
                    columns=columns,
                )

            apply_tags(endpoint, data.tags)

            self._log_activity(
                item_id=str(endpoint.id),
                scope="Endpoint",
                activity="created",
                detail=Detail(name=endpoint.name),
            )

            report_user_action(
                user=self.user,
                event="endpoint created",
                properties={
                    "endpoint_id": str(endpoint.id),
                    "endpoint_name": endpoint.name,
                    "query_kind": query_dict.get("kind") if isinstance(query_dict, dict) else None,
                },
                team=self.team,
                request=self.request,
            )

            return endpoint

        except ValidationError:
            raise
        except Exception as e:
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "endpoint_name": data.name,
                },
            )
            raise ValidationError("Failed to create endpoint.")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        endpoint: Endpoint,
        data: EndpointRequest,
        raw_data: dict,
        version_number: int | None = None,
    ) -> EndpointUpdateResult:
        """Update an endpoint, creating a new version when the query changes.

        When version_number is provided, updates target that specific version
        (and query changes are rejected). ``raw_data`` is the unparsed request
        payload, needed to distinguish omitted fields from explicit nulls.
        """
        endpoint_before_update = Endpoint.objects.get(pk=endpoint.id)

        target_version_override = self._resolve_target_version_override(endpoint, data, version_number)
        version_targeted = target_version_override is not None

        step = "start"
        try:
            current_version = endpoint.get_version()
            # get_version raises when no versions exist, so target_version is never None.
            target_version = target_version_override or current_version
            version_before_update = EndpointVersion.objects.get(pk=target_version.pk)
            was_materialized = current_version.saved_query_id is not None

            step = "endpoint_activation"
            # Endpoint-level activation only — deactivating a single version must never
            # touch the endpoint or the current version's materialization.
            if data.is_active is not None and not version_targeted:
                endpoint.is_active = data.is_active
            endpoint.save()
            if not version_targeted and not endpoint.is_active:
                # A deactivated endpoint serves no version, so none should keep a
                # materialization schedule running — tear down every materialized
                # version, not just the current one.
                for materialized_version in endpoint.versions.filter(saved_query__isnull=False):
                    self.materialization.disable_materialization(endpoint, materialized_version)
            if data.is_active is not None and not version_targeted:
                # Activation affects throttle classification — force a lazy re-check.
                clear_endpoint_materialization_cache(self.team.pk, endpoint.name)

            step = "versioning"
            target_version, version_was_created, old_bucket_overrides = self._apply_query_change(
                endpoint, data, target_version, was_materialized
            )

            step = "version_fields"
            self._apply_version_field_updates(target_version, data, raw_data, version_targeted)

            step = "materialization"
            materialization_error = self._reconcile_materialization(
                endpoint,
                data,
                raw_data,
                target_version,
                version_targeted,
                was_materialized=was_materialized,
                version_was_created=version_was_created,
                old_bucket_overrides=old_bucket_overrides,
            )

            step = "tags_and_activity"
            apply_tags(endpoint, data.tags)
            self._log_update_activity(
                endpoint, endpoint_before_update, target_version, version_before_update, version_was_created
            )

            return EndpointUpdateResult(
                endpoint=endpoint,
                target_version=target_version,
                version_targeted=version_targeted,
                materialization_error=materialization_error,
            )

        except APIException:
            raise
        except ValidationError:
            raise
        except Exception as e:
            current_version = endpoint.get_version()
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "endpoint_id": endpoint.id,
                    "saved_query_id": current_version.saved_query.id if current_version.saved_query else None,
                    "update_step": step,
                },
            )
            raise ValidationError("Failed to update endpoint.")

    def _resolve_target_version_override(
        self, endpoint: Endpoint, data: EndpointRequest, version_number: int | None
    ) -> EndpointVersion | None:
        if version_number is None:
            return None
        try:
            target_version_override = endpoint.get_version(version_number)
        except EndpointVersion.DoesNotExist:
            raise ValidationError({"version": f"Version {version_number} not found for this endpoint."})
        if data.query is not None:
            raise ValidationError(
                {"query": "Cannot change query when targeting a specific version. Query changes create a new version."}
            )
        return target_version_override

    def _apply_query_change(
        self,
        endpoint: Endpoint,
        data: EndpointRequest,
        target_version: EndpointVersion,
        was_materialized: bool,
    ) -> tuple[EndpointVersion, bool, dict[str, str] | None]:
        """Create a new version when the query changed. Returns (target_version, created, old_bucket_overrides)."""
        if data.query is None:
            return target_version, False, None

        new_query_dict = data.query.model_dump()
        if not endpoint.has_query_changed(new_query_dict):
            return target_version, False, None

        # Preserve bucketing across the version bump so materialization transfers cleanly.
        old_bucket_overrides = target_version.bucket_overrides if was_materialized else None
        new_version = endpoint.create_new_version(query=new_query_dict, user=self.user)
        # The "current" version changed — its cached throttle readiness no longer applies.
        clear_endpoint_materialization_cache(self.team.pk, endpoint.name)
        return new_version, True, old_bucket_overrides

    def _apply_version_field_updates(
        self,
        target_version: EndpointVersion,
        data: EndpointRequest,
        raw_data: dict,
        version_targeted: bool,
    ) -> None:
        update_fields = []
        if data.description is not None:
            target_version.description = data.description
            update_fields.append("description")
        if "data_freshness_seconds" in raw_data:
            target_version.data_freshness_seconds = (
                data.data_freshness_seconds
                if data.data_freshness_seconds is not None
                else DEFAULT_DATA_FRESHNESS_SECONDS
            )
            update_fields.append("data_freshness_seconds")
        # When targeting a specific version, is_active updates the version
        if data.is_active is not None and version_targeted:
            target_version.is_active = data.is_active
            update_fields.append("is_active")
        if update_fields:
            update_fields.append("updated_at")
            target_version.save(update_fields=update_fields)

    def _reconcile_materialization(
        self,
        endpoint: Endpoint,
        data: EndpointRequest,
        raw_data: dict,
        target_version: EndpointVersion,
        version_targeted: bool,
        *,
        was_materialized: bool,
        version_was_created: bool,
        old_bucket_overrides: dict[str, str] | None,
    ) -> str | None:
        """Bring the target version's materialization in line with the request.

        Returns a materialization error message when enabling failed after a new
        version was already committed (the update itself still succeeds).
        """
        if version_targeted and not target_version.is_active:
            # Deactivating a version: tear down its own materialization, never enable.
            # Checked before the endpoint-active guard so this holds even on an inactive endpoint.
            if target_version.saved_query_id is not None:
                self.materialization.disable_materialization(endpoint, target_version)
            return None

        if not endpoint.is_active:
            # Endpoint-level deactivation already tore down every version's materialization.
            return None

        # When targeting a specific version, check that version's materialization state.
        # Otherwise use the pre-update state so materialization transfers across a version bump.
        check_was_materialized = target_version.saved_query_id is not None if version_targeted else was_materialized

        should_enable = data.is_materialized is True or (data.is_materialized is None and check_was_materialized)
        if data.is_materialized is False:
            self.materialization.disable_materialization(endpoint, target_version)
            return None
        if not should_enable:
            return None

        bucket_overrides = raw_data.get("bucket_overrides")
        if bucket_overrides is None and version_was_created:
            bucket_overrides = old_bucket_overrides
        validate_bucket_overrides(bucket_overrides)
        stored_bucket_overrides = target_version.bucket_overrides

        try:
            self.materialization.enable_materialization(
                endpoint,
                target_version,
                target_version.data_freshness_seconds,
                bucket_overrides=bucket_overrides,
            )
            if (
                bucket_overrides is not None
                and bucket_overrides != stored_bucket_overrides
                and target_version.saved_query is not None
            ):
                # enable only triggers an immediate Temporal run when it creates the schedule;
                # changed bucketing on an existing materialization needs an explicit refresh.
                try:
                    trigger_saved_query_schedule(target_version.saved_query)
                except Exception:
                    logger.warning(
                        "failed_to_trigger_materialization_refresh",
                        team_id=self.team.pk,
                        endpoint_name=endpoint.name,
                        saved_query_id=str(target_version.saved_query_id),
                        bucket_overrides=bucket_overrides,
                    )
        except Exception as e:
            if not version_was_created:
                raise
            # The new version was already committed — don't fail the whole update.
            # Materialization can be retried via a subsequent update.
            logger.exception(
                "Materialization failed after version creation",
                endpoint_name=endpoint.name,
                version=target_version.version,
            )
            capture_exception(
                e,
                {
                    "product": Product.ENDPOINTS,
                    "team_id": self.team.pk,
                    "endpoint_name": endpoint.name,
                    "version": target_version.version,
                },
            )
            return str(e)
        return None

    def _log_update_activity(
        self,
        endpoint: Endpoint,
        endpoint_before_update: Endpoint,
        target_version: EndpointVersion,
        version_before_update: EndpointVersion,
        version_was_created: bool,
    ) -> None:
        endpoint_changes = changes_between("Endpoint", previous=endpoint_before_update, current=endpoint)
        if endpoint_changes:
            self._log_activity(
                item_id=str(endpoint.id),
                scope="Endpoint",
                activity="updated",
                detail=Detail(name=endpoint.name, changes=endpoint_changes),
            )

        if version_was_created:
            query_change = Change(
                type="EndpointVersion",
                action="changed",
                field="query",
                before=version_before_update.query,
                after=target_version.query,
            )
            self._log_activity(
                item_id=str(endpoint.id),
                scope="Endpoint",
                activity="version_created",
                detail=Detail(
                    name=endpoint.name,
                    changes=[query_change],
                    context=EndpointContext(version=target_version.version),
                ),
            )
        else:
            version_changes = changes_between("EndpointVersion", previous=version_before_update, current=target_version)
            if version_changes:
                self._log_activity(
                    item_id=str(endpoint.id),
                    scope="EndpointVersion",
                    activity="version_updated",
                    detail=Detail(
                        name=endpoint.name,
                        changes=version_changes,
                        context=EndpointContext(version=target_version.version),
                    ),
                )

    # ------------------------------------------------------------------
    # Destroy
    # ------------------------------------------------------------------

    def destroy(self, endpoint: Endpoint) -> None:
        """Soft-delete an endpoint and clean up materialized queries."""
        endpoint_id = str(endpoint.id)
        endpoint_name = endpoint.name

        # DAG cleanup only — the saved queries themselves are reverted and soft-deleted
        # by endpoint.soft_delete() via version.disable_materialization().
        for version in endpoint.versions.filter(saved_query__isnull=False):
            try:
                if version.saved_query:
                    delete_node_from_dag(version.saved_query)
            except Exception as e:
                logger.exception(
                    "Failed to remove endpoint node from DAG on destroy",
                    endpoint_name=endpoint.name,
                    saved_query_id=version.saved_query.id if version.saved_query else None,
                )
                capture_exception(
                    e,
                    {
                        "product": Product.ENDPOINTS,
                        "team_id": self.team.pk,
                        "endpoint_name": endpoint.name,
                        "saved_query_id": version.saved_query.id if version and version.saved_query else None,
                    },
                )

        endpoint.soft_delete()
        clear_endpoint_materialization_cache(
            self.team.pk, endpoint.name, versions=endpoint.versions.values_list("version", flat=True)
        )
        self._log_activity(
            item_id=endpoint_id,
            scope="Endpoint",
            activity="deleted",
            detail=Detail(name=endpoint_name),
        )
