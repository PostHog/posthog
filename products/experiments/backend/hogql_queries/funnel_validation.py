"""
Datawarehouse funnel validation utilities.

This module provides validation for datawarehouse funnel configurations,
ensuring required fields are present, join keys are consistent, and
complexity limits are enforced before query execution.
"""

from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.schema import ExperimentDataWarehouseNode, ExperimentFunnelMetric


class FunnelDWValidator:
    """
    Validates datawarehouse funnel configuration.

    Provides clear, actionable error messages for common DW funnel
    misconfigurations before expensive query execution.

    All methods are static as validation is stateless - operates only
    on the provided metric configuration.
    """

    # Complexity limits to prevent expensive queries
    MAX_DW_STEPS = 3
    MAX_DISTINCT_DW_TABLES = 2

    @staticmethod
    def validate_required_fields(node: ExperimentDataWarehouseNode, step_index: int) -> list[str]:
        """
        Validate DW node has all required fields.

        Args:
            node: The datawarehouse node to validate
            step_index: Step number in funnel (1-based for error messages)

        Returns:
            List of error messages (empty if valid)

        Example:
            >>> errors = FunnelDWValidator.validate_required_fields(node, 2)
            >>> if errors:
            ...     raise ValidationError({"datawarehouse_configuration": errors})
        """
        errors = []

        if not node.table_name:
            errors.append(f"Step {step_index}: table_name is required to identify the datawarehouse table")

        if not node.timestamp_field:
            errors.append(
                f"Step {step_index}: timestamp_field is required for time-based filtering "
                "(e.g., 'created_at', 'purchase_date')"
            )

        if not node.data_warehouse_join_key:
            errors.append(
                f"Step {step_index}: data_warehouse_join_key is required to join with events "
                "(e.g., 'user_id', 'customer_id')"
            )

        if not node.events_join_key:
            errors.append(
                f"Step {step_index}: events_join_key is required to specify the field in PostHog events "
                "(e.g., 'properties.$user_id', 'distinct_id')"
            )

        return errors

    @staticmethod
    def validate_consistent_join_keys(metric: ExperimentFunnelMetric) -> dict[str, str] | None:
        """
        Validate all DW steps use the same events_join_key.

        This is a current limitation that simplifies the UNION ALL query pattern.
        All DW steps must join to events using the same field.

        Args:
            metric: The funnel metric to validate

        Returns:
            Dictionary with error key and message if invalid, None if valid

        Example:
            >>> error = FunnelDWValidator.validate_consistent_join_keys(metric)
            >>> if error:
            ...     raise ValidationError(error)
        """
        dw_steps = [
            (i + 1, step) for i, step in enumerate(metric.series) if isinstance(step, ExperimentDataWarehouseNode)
        ]

        if len(dw_steps) <= 1:
            # 0 or 1 DW steps - no consistency to check
            return None

        # Collect all unique events_join_keys
        join_keys: dict[str, list[int]] = {}
        for step_index, step in dw_steps:
            join_key = step.events_join_key
            if join_key not in join_keys:
                join_keys[join_key] = []
            join_keys[join_key].append(step_index)

        if len(join_keys) > 1:
            # Multiple different join keys - build helpful error message
            error_lines = ["All datawarehouse steps must use the same join key to events.\n"]

            for join_key, step_indices in join_keys.items():
                steps_str = ", ".join(f"Step {idx}" for idx in step_indices)
                error_lines.append(f"{steps_str} use: {join_key}")

            error_lines.append("\nPlease ensure all DW steps join on the same field.")

            return {"join_key_mismatch": "\n".join(error_lines)}

        return None

    @staticmethod
    def validate_complexity_limits(metric: ExperimentFunnelMetric) -> dict[str, str] | None:
        """
        Enforce complexity limits to prevent expensive queries.

        Limits:
        - Max 3 DW steps per funnel (reduces UNION ALL query size)
        - Max 2 distinct DW tables per funnel (limits join complexity)

        Args:
            metric: The funnel metric to validate

        Returns:
            Dictionary with error key and message if limit exceeded, None if valid

        Example:
            >>> error = FunnelDWValidator.validate_complexity_limits(metric)
            >>> if error:
            ...     raise ValidationError(error)
        """
        dw_steps = [step for step in metric.series if isinstance(step, ExperimentDataWarehouseNode)]

        # Check max DW steps
        if len(dw_steps) > FunnelDWValidator.MAX_DW_STEPS:
            return {
                "complexity_limit": (
                    f"Too many datawarehouse steps: {len(dw_steps)} "
                    f"(maximum: {FunnelDWValidator.MAX_DW_STEPS}).\n\n"
                    "Datawarehouse steps create expensive UNION queries. "
                    "Consider using fewer DW steps or creating a materialized view "
                    "that combines your DW tables."
                )
            }

        # Check max distinct tables
        distinct_tables = {step.table_name for step in dw_steps}
        if len(distinct_tables) > FunnelDWValidator.MAX_DISTINCT_DW_TABLES:
            table_list = ", ".join(f"'{table}'" for table in sorted(distinct_tables))
            return {
                "complexity_limit": (
                    f"Too many distinct datawarehouse tables: {len(distinct_tables)} "
                    f"(maximum: {FunnelDWValidator.MAX_DISTINCT_DW_TABLES}).\n\n"
                    f"Tables used: {table_list}\n\n"
                    "Multiple DW tables increase join complexity. "
                    "Consider using a single table or creating a view that joins them."
                )
            }

        return None

    @classmethod
    def validate_funnel_metric(cls, metric: ExperimentFunnelMetric) -> None:
        """
        Run all validations on a funnel metric.

        This is the main entry point - call before building queries for DW funnels.

        Args:
            metric: The funnel metric to validate

        Raises:
            ValidationError: If any validation fails, with detailed error messages

        Example:
            >>> try:
            ...     FunnelDWValidator.validate_funnel_metric(metric)
            ... except ValidationError as e:
            ...     # Show error to user
            ...     return Response(e.detail, status=400)
        """
        errors: dict[str, Any] = {}

        # Check if there are any DW steps
        has_dw_steps = any(isinstance(step, ExperimentDataWarehouseNode) for step in metric.series)

        # If no DW steps, no validation needed
        if not has_dw_steps:
            return

        # 1. Validate required fields for each DW step
        field_errors: list[str] = []
        for i, step in enumerate(metric.series):
            if isinstance(step, ExperimentDataWarehouseNode):
                step_errors = cls.validate_required_fields(step, i + 1)
                field_errors.extend(step_errors)

        if field_errors:
            errors["datawarehouse_configuration"] = field_errors
            errors["help"] = "All DW steps need table name, timestamp field, and join keys configured."
            # Early return - downstream checks are unreliable with missing fields
            raise ValidationError(errors)

        # 2. Validate join key consistency
        join_key_error = cls.validate_consistent_join_keys(metric)
        if join_key_error:
            errors.update(join_key_error)

        # 3. Validate complexity limits
        complexity_error = cls.validate_complexity_limits(metric)
        if complexity_error:
            errors.update(complexity_error)

        # Raise if any errors found
        if errors:
            raise ValidationError(errors)
