"""Request payload validation for endpoint create/update.

These functions validate (and normalize) the ``EndpointRequest`` payload before
it reaches the CRUD service: name format, data freshness buckets, HogQL
parseability, and variable placeholder <-> definition consistency.
"""

import re
import uuid
from typing import Optional

from django.conf import settings

from pydantic import BaseModel
from rest_framework.exceptions import ValidationError

from posthog.schema import EndpointRequest, HogQLQuery, HogQLVariable

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing
from posthog.hogql.variables import replace_variables

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.endpoints.backend.constants import (
    DATA_FRESHNESS_BUCKET_SPECS,
    ENDPOINT_NAME_REGEX,
    VALID_DATA_FRESHNESS_SECONDS,
)
from products.endpoints.backend.logic.strategies import BREAKDOWN_SUPPORTED_QUERY_TYPES
from products.endpoints.backend.materialization_transforms import SUPPORTED_BUCKET_FUNCTIONS, VariablePlaceholderFinder
from products.endpoints.backend.models import (
    Endpoint,
    EndpointVersion,
    _breakdown_property_names,
    can_materialize_query,
)
from products.product_analytics.backend.models.insight_variable import InsightVariable


def validate_data_freshness(data_freshness_seconds: int | None) -> None:
    """Validate data_freshness_seconds is one of the allowed bucket values."""
    if data_freshness_seconds is None:
        return
    if data_freshness_seconds not in VALID_DATA_FRESHNESS_SECONDS:
        allowed = sorted(VALID_DATA_FRESHNESS_SECONDS)
        human = ", ".join(b.human for b in DATA_FRESHNESS_BUCKET_SPECS)
        raise ValidationError(
            {"data_freshness_seconds": f"Data freshness must be one of: {allowed} seconds ({human})."}
        )


def validate_bucket_overrides(bucket_overrides: dict[str, str] | None) -> None:
    """Raise ValidationError if any bucket override value is not in SUPPORTED_BUCKET_FUNCTIONS."""
    if not bucket_overrides:
        return

    invalid = {k: v for k, v in bucket_overrides.items() if v not in SUPPORTED_BUCKET_FUNCTIONS}
    if invalid:
        valid_options = list(SUPPORTED_BUCKET_FUNCTIONS.keys())
        raise ValidationError(f"Invalid bucket override values: {invalid}. Valid options: {valid_options}")


def validate_hogql_query(query: HogQLQuery, team: Team, user: User) -> None:
    """Validate that a HogQL query parses, its variables are valid, and the author can
    access every table/view it references."""
    try:
        ast_node = parse_select(query.query)
    except ExposedHogQLError as e:
        raise ValidationError({"query": f"Invalid HogQL query: {e}"}) from e
    except ResolutionError as e:
        capture_exception(e)
        raise ValidationError({"query": "Invalid HogQL query: unable to resolve table or field references."})
    except Exception as e:
        capture_exception(e)
        raise ValidationError({"query": "Unknown error occurred parsing the query."})

    validate_variable_placeholders(ast_node, query.variables or {}, team)

    _validate_query_access(ast_node, query, team, user)


def _validate_query_access(
    ast_node: ast.SelectQuery | ast.SelectSetQuery,
    query: HogQLQuery,
    team: Team,
    user: User,
) -> None:
    """Resolve the query under the author's access control; raise if it hits a denied table/view."""
    resolvable_ast: ast.Expr = ast_node
    if query.variables:
        # Substitute {variables.x} so the AST resolves (endpoints allow variables; views don't).
        # Missing definitions were already caught by validate_variable_placeholders above.
        resolvable_ast = replace_variables(ast_node, list(query.variables.values()), team)

    context = HogQLContext(team_id=team.pk, user=user, enable_select_queries=True)
    try:
        # Using prepare_ast_for_printing instead of prepare_and_print_ast
        # because table/view access is enforced during resolution
        prepare_ast_for_printing(node=resolvable_ast, context=context, dialect="clickhouse")
    except ExposedHogQLError as err:
        # Surfaces "You don't have access to table `X`." (QueryError) and other resolver errors.
        raise ValidationError({"query": f"Invalid HogQL query: {err}"}) from err
    except Exception as err:
        capture_exception(err)
        if not settings.DEBUG:
            raise ValidationError({"query": f"Unexpected {err.__class__.__name__}"})
        raise


def sync_hogql_query_variables(query: HogQLQuery, team: Team) -> None:
    """Sync query variable definitions with the placeholders used in the query string."""
    try:
        ast_node = parse_select(query.query)
    except Exception:
        # Validation runs separately and will surface parse errors.
        return

    finder = VariablePlaceholderFinder()
    finder.visit(ast_node)

    placeholder_names = {str(p.chain[1]) for p in finder.variable_placeholders if p.chain and len(p.chain) > 1}
    if not placeholder_names:
        query.variables = None
        return

    existing_variables = query.variables or {}
    existing_variable_ids: list[str] = []
    for variable in existing_variables.values():
        if not variable.variableId:
            continue
        try:
            uuid.UUID(variable.variableId)
        except ValueError:
            continue
        existing_variable_ids.append(variable.variableId)

    team_variables = InsightVariable.objects.filter(team=team, id__in=existing_variable_ids)
    team_variables_by_id = {str(variable.id): variable for variable in team_variables}

    synced_variables: dict[str, HogQLVariable] = {}
    existing_code_names: set[str] = set()

    for variable_id, variable in existing_variables.items():
        if variable.code_name and variable.code_name in placeholder_names:
            if variable.value is None and variable.isNull is not True:
                team_variable = team_variables_by_id.get(variable.variableId)
                if team_variable:
                    variable.value = team_variable.default_value
                    variable.isNull = team_variable.default_value is None
            synced_variables[variable_id] = variable
            existing_code_names.add(variable.code_name)

    missing_code_names = placeholder_names - existing_code_names
    if missing_code_names:
        missing_variables = InsightVariable.objects.filter(team=team, code_name__in=missing_code_names)

        for variable in missing_variables:
            if not variable.code_name:
                continue
            synced_variables[str(variable.id)] = HogQLVariable(
                variableId=str(variable.id),
                code_name=variable.code_name,
                value=variable.default_value,
                isNull=variable.default_value is None,
            )

    query.variables = synced_variables or None


def validate_variable_placeholders(node: ast.AST, variables: Optional[dict[str, HogQLVariable]], team: Team) -> None:
    """Validate that every {variables.X} placeholder in the query has a matching variable definition."""
    finder = VariablePlaceholderFinder()
    finder.visit(node)

    if not finder.variable_placeholders:
        return

    placeholder_names = {str(p.chain[1]) for p in finder.variable_placeholders if p.chain and len(p.chain) > 1}

    defined_code_names: set[str] = set()
    variable_ids: set[str] = set()
    if variables:
        defined_code_names = {v.code_name for v in variables.values() if v.code_name}
        variable_ids = set(variables.keys())

    undefined: list[str] = sorted(placeholder_names - defined_code_names)
    if undefined:
        raise ValidationError(
            {
                "query": f"Query references undefined variable(s): {', '.join(undefined)}. "
                "See https://posthog.com/docs/endpoints/variables for detail."
            }
        )

    if variable_ids:
        valid_uuids: set[str] = set()
        invalid_uuids: set[str] = set()
        invalid_ids: set[str] = set()
        for vid in variable_ids:
            try:
                uuid.UUID(vid)
                valid_uuids.add(vid)
            except ValueError:
                invalid_uuids.add(vid)

        if invalid_uuids:
            raise ValidationError({"query": f"Variable ID(s) not valid UUIDs: {', '.join(sorted(invalid_uuids))}. "})

        if valid_uuids:
            existing_ids = {
                str(id)
                for id in InsightVariable.objects.filter(team=team, id__in=valid_uuids).values_list("id", flat=True)
            }
            invalid_ids = valid_uuids - existing_ids

        if invalid_ids:
            raise ValidationError(
                {
                    "query": f"Variable ID(s) not found: {', '.join(sorted(invalid_ids))}. "
                    "Make sure the variables exist in https://app.posthog.com/data-management/variables."
                }
            )


def validate_optional_breakdown_properties(
    optional_breakdown_properties: list[str] | None,
    query: BaseModel | dict | None,
) -> None:
    """Reject optional_breakdown_properties when the query has no breakdownFilter, or when
    any name isn't an actual breakdown property in the query.

    ``query`` is any of ``EndpointRequest.query``'s pydantic models, or a stored version's
    query dict — typed by contract so this doesn't chase the growing query-kind union.
    """
    if not optional_breakdown_properties:
        return

    query_dict = query.model_dump() if isinstance(query, BaseModel) else query
    query_kind = query_dict.get("kind") if isinstance(query_dict, dict) else None
    if query_kind not in BREAKDOWN_SUPPORTED_QUERY_TYPES:
        raise ValidationError(
            {
                "optional_breakdown_properties": (
                    f"Query kind {query_kind!r} does not support breakdowns. "
                    f"Supported: {', '.join(sorted(BREAKDOWN_SUPPORTED_QUERY_TYPES))}."
                )
            }
        )

    breakdown_filter = (query_dict.get("breakdownFilter") if isinstance(query_dict, dict) else None) or {}
    known = set(_breakdown_property_names(breakdown_filter))
    unknown = [p for p in optional_breakdown_properties if p not in known]
    if unknown:
        raise ValidationError(
            {
                "optional_breakdown_properties": (
                    f"Unknown breakdown propert{'y' if len(unknown) == 1 else 'ies'}: "
                    f"{', '.join(repr(p) for p in unknown)}. "
                    f"Known: {sorted(known) if known else '(none)'}."
                )
            }
        )


def validate_endpoint_request(data: EndpointRequest, team: Team, user: User, strict: bool = True) -> None:
    """Validate a create/update payload. With strict=True, name and query are required."""
    query = data.query
    if not query and strict:
        raise ValidationError({"query": "This field is required."})

    name = data.name
    if not name:
        if name is not None or strict:
            raise ValidationError({"name": "This field is required."})
        return
    if not isinstance(name, str) or not re.fullmatch(ENDPOINT_NAME_REGEX, name):
        raise ValidationError(
            {
                "name": f"Invalid name '{name}'. Must start with a letter, contain only alphanumeric characters, "
                "hyphens, or underscores, and be between 1 and 128 characters long."
            }
        )

    if query and isinstance(query, HogQLQuery) and query.query:
        sync_hogql_query_variables(query, team)
        validate_hogql_query(query, team, user)

    validate_data_freshness(data.data_freshness_seconds)
    validate_optional_breakdown_properties(data.optional_breakdown_properties, query)


def validate_update_request(
    data: EndpointRequest,
    team: Team,
    user: User,
    endpoint: Endpoint | None = None,
    version_number: int | None = None,
) -> None:
    """Validate an update payload against the endpoint's resulting state."""
    validate_data_freshness(data.data_freshness_seconds)

    # Determine final states after this request (for validation)
    will_be_active = data.is_active if data.is_active is not None else (endpoint.is_active if endpoint else True)

    if not will_be_active and data.is_materialized is True:
        raise ValidationError({"is_materialized": "Cannot enable materialization on inactive endpoint."})

    if data.is_materialized is True:
        # Fail fast on queries that can't be materialized. The service re-checks against
        # the final version (the authoritative guard); this catches it before any writes.
        effective_query = (
            data.query.model_dump() if data.query is not None else (endpoint.get_version().query if endpoint else None)
        )
        if effective_query is not None:
            can_materialize, reason = can_materialize_query(effective_query)
            if not can_materialize:
                raise ValidationError(f"Cannot materialize endpoint. Reason: {reason}")

    if data.query and isinstance(data.query, HogQLQuery) and data.query.query:
        sync_hogql_query_variables(data.query, team)
        validate_hogql_query(data.query, team, user)

    # Validate optional_breakdown_properties against the post-update query when one is supplied,
    # otherwise against the query of the version the update writes to (targeted or current).
    if data.optional_breakdown_properties is not None:
        if data.query is not None:
            validate_optional_breakdown_properties(data.optional_breakdown_properties, data.query)
        elif endpoint is not None:
            try:
                target_query = endpoint.get_version(version_number).query
            except EndpointVersion.DoesNotExist:
                target_query = None  # a nonexistent targeted version 404s in the update service
            if target_query is not None:
                validate_optional_breakdown_properties(data.optional_breakdown_properties, target_query)
