from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from django.conf import settings

import dagster
from dagster._core.definitions.metadata import RawMetadataMapping
from dagster_slack import SlackResource
from pydantic import BaseModel, Field, ValidationError

from posthog.dags.common import JobOwners

from products.llm_analytics.backend.models import Dataset, DatasetItem
from products.posthog_ai.dags.snapshot_team_data import PostgresTeamDataSnapshot, snapshot_postgres_team_data
from products.posthog_ai.dags.utils import EvaluationResults, format_results

from ee.hogai.eval.online.aurora_manager import AuroraEvalDatabaseManager
from ee.hogai.eval.schema import DatasetInput, EvalsDockerImageConfig, TeamEvaluationSnapshot


def _get_aurora_manager() -> AuroraEvalDatabaseManager:
    return AuroraEvalDatabaseManager(
        host=settings.EVAL_AURORA_HOST,
        port=settings.EVAL_AURORA_PORT,
        admin_user=settings.EVAL_AURORA_ADMIN_USER,
        admin_password=settings.EVAL_AURORA_ADMIN_PASSWORD,
        admin_database=settings.EVAL_AURORA_ADMIN_DATABASE,
    )


def _get_team_id() -> int:
    return 2 if not settings.DEBUG else 1


class AgentPrepareDatasetConfig(dagster.Config):
    dataset_id: str


class AgentPreparedDataset(BaseModel):
    dataset_id: UUID
    dataset_name: str
    dataset_inputs: list[DatasetInput]


@dagster.op(
    description="Pulls agent eval dataset and validates inputs.",
)
def agent_prepare_dataset(
    context: dagster.OpExecutionContext, config: AgentPrepareDatasetConfig
) -> AgentPreparedDataset:
    dataset = Dataset.objects.exclude(deleted=True).get(id=config.dataset_id, team_id=_get_team_id())
    dataset_items = DatasetItem.objects.exclude(deleted=True).filter(dataset=dataset).iterator(500)

    dataset_inputs: list[DatasetInput] = []
    for dataset_item in dataset_items:
        try:
            metadata = dataset_item.metadata or {}
            dataset_inputs.append(
                DatasetInput(
                    input=dataset_item.input,
                    expected=dataset_item.output,
                    metadata=metadata,
                    team_id=metadata.get("team_id"),
                )
            )
        except ValidationError:
            context.log.exception(f"Validation error for dataset item {dataset_item.id}")
            raise

    return AgentPreparedDataset(
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        dataset_inputs=dataset_inputs,
    )


@dagster.op(out=dagster.DynamicOut(int))
def agent_prepare_evaluation(prepared_dataset: AgentPreparedDataset):
    seen_teams: set[int] = set()
    for dataset_input in prepared_dataset.dataset_inputs:
        if dataset_input.team_id in seen_teams:
            continue
        seen_teams.add(dataset_input.team_id)
        yield dagster.DynamicOutput(dataset_input.team_id, mapping_key=str(dataset_input.team_id))


@dagster.op(
    description="Creates a per-eval-run database on Aurora and returns the database name.",
    tags={"owner": JobOwners.TEAM_POSTHOG_AI.value},
)
def create_aurora_eval_database(context: dagster.OpExecutionContext) -> str:
    manager = _get_aurora_manager()
    db_name = manager.create_eval_database(context.run_id)
    context.log.info(f"Created Aurora eval database: {db_name}")
    return db_name


@dagster.op(
    description="Drops the Aurora eval database after the run completes.",
    tags={"owner": JobOwners.TEAM_POSTHOG_AI.value},
)
def cleanup_aurora_eval_database(context: dagster.OpExecutionContext, eval_db_name: str) -> None:
    manager = _get_aurora_manager()
    manager.cleanup_eval_database(eval_db_name)
    context.log.info(f"Cleaned up Aurora eval database: {eval_db_name}")


class AgentEvaluationConfig(dagster.Config):
    image_name: str = Field(description="Name of the Docker image to run.")
    image_tag: str = Field(description="Tag of the Docker image to run.")
    evaluation_module: str = Field(description="Python module containing the evaluation runner.")

    @property
    def image(self) -> str:
        if settings.DEBUG:
            return f"{self.image_name}:{self.image_tag}"
        return f"{dagster.EnvVar('AWS_EKS_REGISTRY_URL').get_value()}/{self.image_name}:{self.image_tag}"


def unpack_evaluation_results(metadata: RawMetadataMapping | None) -> EvaluationResults | None:
    if not metadata:
        return None
    try:
        meta = metadata["evaluation_results"]
        if isinstance(meta, dagster.JsonMetadataValue):
            return cast(list[dict[Any, Any]], meta.value)
        return None
    except KeyError:
        return None


def get_last_dataset_materialization_metadata(
    context: dagster.OpExecutionContext, asset_key: dagster.AssetKey
) -> EvaluationResults | None:
    last_materialization_event = context.instance.get_latest_materialization_event(asset_key)
    if not last_materialization_event or not last_materialization_event.asset_materialization:
        return None
    return unpack_evaluation_results(last_materialization_event.asset_materialization.metadata)


@dagster.op(
    description="Launches agent eval as a k8s job with production CH + Aurora credentials.",
    tags={
        "owner": JobOwners.TEAM_POSTHOG_AI.value,
        "dagster/max_runtime": 60 * 60,
    },
)
def spawn_agent_eval_job(
    context: dagster.OpExecutionContext,
    config: AgentEvaluationConfig,
    slack: SlackResource,
    prepared_dataset: AgentPreparedDataset,
    team_ids: list[int],
    postgres_snapshots: list[PostgresTeamDataSnapshot],
    eval_db_name: str,
):
    if not config.evaluation_module.endswith(".py"):
        raise ValueError("Evaluation module must be a Python file")
    if not config.evaluation_module.startswith("ee/hogai/eval/"):
        raise ValueError(f"Evaluation module {config.evaluation_module} must start with 'ee/hogai/eval/'")

    snapshot_date = datetime.now(tz=UTC).isoformat()

    asset_key = dagster.AssetKey(["agent_evaluation_dataset", str(prepared_dataset.dataset_id)])
    evaluation_config = EvalsDockerImageConfig(
        aws_endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        aws_bucket_name=settings.OBJECT_STORAGE_BUCKET,
        team_snapshots=[
            TeamEvaluationSnapshot(
                team_id=team_id,
                postgres=postgres,
                # No ClickHouse snapshots — agent queries CH directly
                clickhouse={"event_taxonomy": "", "properties_taxonomy": "", "actors_property_taxonomy": ""},
            ).model_dump()
            for team_id, postgres in zip(team_ids, postgres_snapshots)
        ],
        experiment_id=context.run_id,
        experiment_name=f"agent-dataset-{prepared_dataset.dataset_id}",
        dataset_id=str(prepared_dataset.dataset_id),
        dataset_name=prepared_dataset.dataset_name,
        dataset_inputs=prepared_dataset.dataset_inputs,
        snapshot_date=snapshot_date,
    )

    env: dict[str, str] = {
        "EVAL_SCRIPT": f"pytest {config.evaluation_module} -s -vv",
        # Production ClickHouse OFFLINE cluster (read-only)
        "CLICKHOUSE_HOST": settings.CLICKHOUSE_HOST,
        "CLICKHOUSE_SECURE": "true",
        # Aurora for system tables (CH postgresql() function connects here via proxy)
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_HOST": settings.EVAL_AURORA_HOST,
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_PORT": settings.EVAL_AURORA_PORT,
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_DATABASE": eval_db_name,
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_USER": settings.EVAL_AURORA_ADMIN_USER,
        "CLICKHOUSE_HOGQL_RDSPROXY_READ_PASSWORD": settings.EVAL_AURORA_ADMIN_PASSWORD,
        # Django ORM -> same Aurora database
        "DATABASE_URL": (
            f"postgres://{settings.EVAL_AURORA_ADMIN_USER}:{settings.EVAL_AURORA_ADMIN_PASSWORD}"
            f"@{settings.EVAL_AURORA_HOST}:{settings.EVAL_AURORA_PORT}/{eval_db_name}"
        ),
        # Date freezing
        "EVAL_SNAPSHOT_DATE": snapshot_date,
        # S3 access for loading Avro snapshots
        "OBJECT_STORAGE_ACCESS_KEY_ID": settings.OBJECT_STORAGE_ACCESS_KEY_ID,
        "OBJECT_STORAGE_SECRET_ACCESS_KEY": settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
        # LLM API keys
        "OPENAI_API_KEY": settings.OPENAI_API_KEY,
        "ANTHROPIC_API_KEY": settings.ANTHROPIC_API_KEY,
    }
    if settings.OPENAI_BASE_URL:
        env["OPENAI_BASE_URL"] = settings.OPENAI_BASE_URL

    context.log.info(f"Running agent evaluation with image: {config.image}")
    context.log.info(f"Using Aurora database: {eval_db_name}")
    context.log.info(f"Snapshot date: {snapshot_date}")

    # TODO: Replace PipesDockerClient with k8s job launcher when infra is ready.
    # For now, use the same Docker approach as offline evals.
    from dagster_docker import PipesDockerClient

    docker_pipes_client = PipesDockerClient()

    asset_result = docker_pipes_client.run(
        context=context,
        image=config.image,
        container_kwargs={"auto_remove": True},
        env=env,
        extras=evaluation_config.model_dump(exclude_unset=True),
    ).get_materialize_result()

    previous_results = get_last_dataset_materialization_metadata(context, asset_key)
    new_results = unpack_evaluation_results(asset_result.metadata)

    if not new_results:
        context.log.error("No new evaluation results returned")
        raise ValueError("No new evaluation results found")

    blocks, formatted_markdown = format_results(
        prepared_dataset.dataset_id, prepared_dataset.dataset_name, context.run_id, new_results, previous_results
    )
    try:
        slack.get_client().chat_postMessage(channel="#evals-max-ai", blocks=blocks)
    except Exception as e:
        context.log.exception(f"Failed to send Slack notification: {str(e)}")

    context.log_event(
        dagster.AssetMaterialization(
            asset_key=asset_key,
            metadata={
                "evaluation_results": dagster.JsonMetadataValue(new_results),
                "report": dagster.MarkdownMetadataValue(formatted_markdown),
            },
            tags={"owner": JobOwners.TEAM_POSTHOG_AI.value},
        )
    )


@dagster.job(
    description="Runs an agent AI evaluation with production ClickHouse + Aurora Postgres",
    tags={
        "owner": JobOwners.TEAM_POSTHOG_AI.value,
        "dagster/max_runtime": 60 * 60,
    },
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 4}),
    config=dagster.RunConfig(
        ops={
            "agent_prepare_dataset": AgentPrepareDatasetConfig(dataset_id=""),
            "spawn_agent_eval_job": AgentEvaluationConfig(
                evaluation_module="ee/hogai/eval/online/",
                image_name="posthog-agent-evals",
                image_tag="master",
            ),
        }
    ),
)
def run_agent_evaluation():
    prepared_dataset = agent_prepare_dataset()
    team_ids = agent_prepare_evaluation(prepared_dataset)
    postgres_snapshots = team_ids.map(snapshot_postgres_team_data)
    eval_db_name = create_aurora_eval_database()
    spawn_agent_eval_job(
        prepared_dataset,
        team_ids.collect(),
        postgres_snapshots.collect(),
        eval_db_name,
    )
    cleanup_aurora_eval_database(eval_db_name)
