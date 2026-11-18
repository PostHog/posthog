from typing import Any

from rest_framework.exceptions import ValidationError

from posthog.schema import ExperimentDataWarehouseNode, ExperimentFunnelMetric


class FunnelDWValidator:
    """
    Validates a data warehouse funnel configuration before the query runs, so that
    a misconfiguration gets an actionable error message instead of an expensive
    or failed query.
    """

    # Complexity limits to prevent expensive queries
    MAX_DW_STEPS = 3
    MAX_DISTINCT_DW_TABLES = 2

    @staticmethod
    def validate_required_fields(node: ExperimentDataWarehouseNode, step_index: int) -> list[str]:
        """`step_index` is 1-based because it appears in the error messages."""
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
        """All DW steps must use the same events_join_key, which keeps the UNION ALL query simple."""
        dw_steps = [
            (i + 1, step) for i, step in enumerate(metric.series) if isinstance(step, ExperimentDataWarehouseNode)
        ]

        if len(dw_steps) <= 1:
            return None

        join_keys: dict[str, list[int]] = {}
        for step_index, step in dw_steps:
            join_key = step.events_join_key
            if join_key not in join_keys:
                join_keys[join_key] = []
            join_keys[join_key].append(step_index)

        if len(join_keys) > 1:
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
        Each DW step adds a subquery to the UNION ALL, and each distinct DW table
        adds a join, so both counts have a limit.
        """
        dw_steps = [step for step in metric.series if isinstance(step, ExperimentDataWarehouseNode)]

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
        """Entry point to call before building the query. A funnel without DW steps always passes."""
        errors: dict[str, Any] = {}

        has_dw_steps = any(isinstance(step, ExperimentDataWarehouseNode) for step in metric.series)

        if not has_dw_steps:
            return

        field_errors: list[str] = []
        for i, step in enumerate(metric.series):
            if isinstance(step, ExperimentDataWarehouseNode):
                step_errors = cls.validate_required_fields(step, i + 1)
                field_errors.extend(step_errors)

        if field_errors:
            errors["datawarehouse_configuration"] = field_errors
            errors["help"] = "All DW steps need table name, timestamp field, and join keys configured."
            # Raise now, because the join key and complexity checks read these fields
            raise ValidationError(errors)

        join_key_error = cls.validate_consistent_join_keys(metric)
        if join_key_error:
            errors.update(join_key_error)

        complexity_error = cls.validate_complexity_limits(metric)
        if complexity_error:
            errors.update(complexity_error)

        if errors:
            raise ValidationError(errors)
