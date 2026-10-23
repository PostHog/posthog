from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Literal
from uuid import uuid4

from django.db import models

from posthog.dataclasses import frozen
from posthog.models.integration import Integration

from products.batch_exports.backend.facade import api as batch_exports_api
from products.batch_exports.backend.facade.contracts import (
    DestinationTestStep,
    DestinationTestStepResult,
    UnsupportedDestinationTestError,
)
from products.warehouse_sources.backend.facade.models import ExternalDataDestination
from products.warehouse_sources.backend.presentation.destination_connection_check import (
    CONFIG_FAILURES,
    DestinationConnectionCheckError,
    check_postgres_destination,
)

# The BigQuery and Databricks steps create and then drop scratch objects named `<table>_test` in the
# customer's warehouse. Each run gets its own random table name, so the cleanup can never drop an
# object the customer already has.
CONNECTION_TEST_TABLE_PREFIX = "posthog_destination_check"


def new_connection_test_table() -> str:
    return f"{CONNECTION_TEST_TABLE_PREFIX}_{uuid4().hex[:12]}"


class DestinationConnectionTestStepStatus(models.TextChoices):
    PASSED = "Passed"
    FAILED = "Failed"
    SKIPPED = "Skipped"


@frozen
class ConnectionTestFailure:
    step_name: str
    message: str
    field: Literal["integration", "config"]

    def __str__(self) -> str:
        return f"{self.step_name}: {self.message}"


@frozen
class ConnectionTestRun:
    steps: tuple[DestinationTestStep, ...]
    failure: ConnectionTestFailure | None


def _strip_slashes(value: Any) -> str | None:
    if not value:
        return None
    return str(value).strip("/") or None


def _bigquery_config(config: Mapping[str, Any], test_table: str) -> dict[str, object]:
    # The facade merges the integration's config over this, so `project_id` is always the
    # integration's project. The writer also uses that project when the destination names none.
    return {
        "project_id": config.get("project") or config.get("project_id") or None,
        "dataset_id": config.get("dataset") or config.get("dataset_id") or None,
        "table_id": test_table,
    }


def _s3_config(config: Mapping[str, Any], _test_table: str) -> dict[str, object]:
    return {
        "bucket_name": _strip_slashes(config.get("bucket") or config.get("bucket_name")),
        "region": (config.get("region") or "").strip() or None,
    }


def _azure_blob_config(config: Mapping[str, Any], _test_table: str) -> dict[str, object]:
    return {"container_name": _strip_slashes(config.get("container_name") or config.get("container"))}


def _snowflake_config(config: Mapping[str, Any], _test_table: str) -> dict[str, object]:
    return {
        "database": config.get("database") or None,
        "schema": config.get("schema") or "PUBLIC",
        "warehouse": config.get("warehouse") or None,
        "role": config.get("role") or None,
    }


def _databricks_config(config: Mapping[str, Any], test_table: str) -> dict[str, object]:
    return {
        "catalog": config.get("catalog") or "main",
        "schema": config.get("schema") or "default",
        "http_path": config.get("http_path") or None,
        "table_name": test_table,
    }


# Defaults and key aliases mirror each warehouse writer, so the test checks the same target the
# sync writes to.
_CONFIG_ADAPTERS: dict[str, Callable[[Mapping[str, Any], str], dict[str, object]]] = {
    str(ExternalDataDestination.Type.BIGQUERY): _bigquery_config,
    str(ExternalDataDestination.Type.S3): _s3_config,
    str(ExternalDataDestination.Type.AZURE_BLOB): _azure_blob_config,
    str(ExternalDataDestination.Type.SNOWFLAKE): _snowflake_config,
    str(ExternalDataDestination.Type.DATABRICKS): _databricks_config,
}

_TEST_TYPES: dict[str, str] = {
    # The writer creates a missing dataset, so BigQuery uses the test that accepts one it can create.
    str(ExternalDataDestination.Type.BIGQUERY): "BigQueryCreateDataset",
    str(ExternalDataDestination.Type.AZURE_BLOB): "AzureBlob",
    str(ExternalDataDestination.Type.SNOWFLAKE): "Snowflake",
    str(ExternalDataDestination.Type.DATABRICKS): "Databricks",
}

# The first steps of each test check the credentials on the integration. The steps after them
# check the target named in the destination's config.
_CREDENTIAL_STEP_COUNT: dict[str, int] = {
    "BigQueryCreateDataset": 3,
    "AwsS3": 1,
    "S3Compatible": 0,
    "AzureBlob": 0,
    "Snowflake": 1,
    "Databricks": 1,
}


def connection_test_type(destination_type: str, integration: Integration) -> str | None:
    """The batch exports test that covers this destination, or None when there is none."""
    if destination_type == ExternalDataDestination.Type.S3:
        return "AwsS3" if integration.kind == Integration.IntegrationKind.AWS_S3 else "S3Compatible"
    return _TEST_TYPES.get(destination_type)


def run_connection_test(
    destination_type: str, integration: Integration, config: Mapping[str, Any] | None
) -> ConnectionTestRun | None:
    """Run each step of the destination's connection test, and stop at the first failed step.

    Returns None when no test covers this destination type. Steps after a failure stay in the
    result with no result of their own.
    """
    test_type = connection_test_type(destination_type, integration)
    if test_type is None:
        return None

    try:
        described = batch_exports_api.describe_destination_test(test_type)
    except UnsupportedDestinationTestError:
        return None

    test_config = _CONFIG_ADAPTERS[destination_type](
        config if isinstance(config, Mapping) else {}, new_connection_test_table()
    )
    steps = list(described.steps)
    for index in range(len(steps)):
        step = batch_exports_api.run_destination_test_step(
            integration.team_id,
            destination_type=test_type,
            config=test_config,
            integration_id=integration.id,
            step=index,
        )
        steps[index] = step
        if step.result is not None and step.result.status == DestinationConnectionTestStepStatus.FAILED:
            field: Literal["integration", "config"] = (
                "integration" if index < _CREDENTIAL_STEP_COUNT.get(test_type, 0) else "config"
            )
            failure = ConnectionTestFailure(
                step_name=step.name,
                message=step.result.message or "The step failed. Check the destination settings and try again.",
                field=field,
            )
            return ConnectionTestRun(steps=tuple(steps), failure=failure)

    return ConnectionTestRun(steps=tuple(steps), failure=None)


_POSTGRES_STEP = DestinationTestStep(
    name="Connect to Postgres",
    description="Connect to the server and check that the user can create tables in the schema.",
    result=None,
)


def run_postgres_connection_test(integration: Integration, config: Mapping[str, Any] | None) -> ConnectionTestRun:
    """Run the Postgres check as a single step, so it reports like the other connection tests."""
    try:
        check_postgres_destination(integration, dict(config) if isinstance(config, Mapping) else None)
    except DestinationConnectionCheckError as error:
        step = replace(
            _POSTGRES_STEP,
            result=DestinationTestStepResult(
                status=DestinationConnectionTestStepStatus.FAILED.value, message=str(error)
            ),
        )
        failure = ConnectionTestFailure(
            step_name=step.name,
            message=str(error),
            field="config" if error.failure in CONFIG_FAILURES else "integration",
        )
        return ConnectionTestRun(steps=(step,), failure=failure)

    step = replace(
        _POSTGRES_STEP,
        result=DestinationTestStepResult(status=DestinationConnectionTestStepStatus.PASSED.value, message=None),
    )
    return ConnectionTestRun(steps=(step,), failure=None)
