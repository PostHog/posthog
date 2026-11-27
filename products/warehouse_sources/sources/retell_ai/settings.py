from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, frozen, incremental_field

BASE_URL = "https://api.retellai.com"
PAGE_SIZE = 100
INCREMENTAL_LOOKBACK_SECONDS = 3600


@frozen
class RetellAIParent:
    id_field: str
    path: str | None = None
    # Reads the parents from another fan-out table instead of a listing path.
    table: str | None = None
    method: Literal["GET", "POST"] = "GET"
    # Query params naming the parent on the child request. A `{id}` value is replaced by the parent id and a
    # `{version}` value by the parent version. A param whose version is missing on the parent row is left out.
    child_params: tuple[tuple[str, str], ...] = ()
    # Walks the children of each version of the parent, not only of the latest version.
    version_field: str | None = None


@frozen
class RetellAIEndpoint:
    path: str
    primary_key: str | tuple[str, ...]
    method: Literal["GET", "POST"] = "GET"
    pagination_location: Literal["query", "json"] = "query"
    paginated: bool = True
    partition_key: str | None = None
    sortable: bool = True
    sort_order: str = "ascending"
    parents: tuple[RetellAIParent, ...] = ()
    # Copies the parent id onto each child row under the parent's id field.
    include_parent_id: bool = False

    @property
    def primary_keys(self) -> list[str]:
        return [self.primary_key] if isinstance(self.primary_key, str) else list(self.primary_key)


ENDPOINTS: dict[str, RetellAIEndpoint] = {
    "calls": RetellAIEndpoint(
        path="/{api_version}/list-calls",
        primary_key="call_id",
        method="POST",
        pagination_location="json",
        partition_key="start_timestamp",
    ),
    "agents": RetellAIEndpoint(path="/v2/list-agents", primary_key="agent_id", method="POST"),
    "chats": RetellAIEndpoint(
        path="/{api_version}/list-chats",
        primary_key="chat_id",
        method="POST",
        pagination_location="json",
        partition_key="start_timestamp",
    ),
    "phone_numbers": RetellAIEndpoint(path="/v2/list-phone-numbers", primary_key="phone_number"),
    "voices": RetellAIEndpoint(path="/list-voices", primary_key="voice_id", paginated=False),
    "agent_versions": RetellAIEndpoint(
        path="/list-agent-versions/{id}",
        primary_key=("agent_id", "version"),
        parents=(RetellAIParent(id_field="agent_id", path="/v2/list-agents", method="POST"),),
        include_parent_id=True,
    ),
    # Retell lists test case definitions per response engine, so the source walks every Retell LLM and conversation flow.
    "test_case_definitions": RetellAIEndpoint(
        path="/v2/list-test-case-definitions",
        primary_key="test_case_definition_id",
        sortable=False,
        parents=(
            RetellAIParent(
                id_field="llm_id",
                path="/v2/list-retell-llms",
                child_params=(("type", "retell-llm"), ("llm_id", "{id}")),
            ),
            RetellAIParent(
                id_field="conversation_flow_id",
                path="/v2/list-conversation-flows",
                child_params=(("type", "conversation-flow"), ("conversation_flow_id", "{id}")),
            ),
        ),
    ),
    "contacts": RetellAIEndpoint(
        path="/list-contacts",
        primary_key="contact_id",
        method="POST",
        pagination_location="json",
        sort_order="asc",
    ),
    # Retell lists batch tests per response engine version and defaults to the latest version.
    "batch_tests": RetellAIEndpoint(
        path="/v2/list-batch-tests",
        primary_key="test_case_batch_job_id",
        sortable=False,
        parents=(
            RetellAIParent(
                id_field="llm_id",
                path="/v2/list-retell-llms",
                version_field="version",
                child_params=(("type", "retell-llm"), ("llm_id", "{id}"), ("version", "{version}")),
            ),
            RetellAIParent(
                id_field="conversation_flow_id",
                path="/v2/list-conversation-flows",
                version_field="version",
                child_params=(
                    ("type", "conversation-flow"),
                    ("conversation_flow_id", "{id}"),
                    ("version", "{version}"),
                ),
            ),
        ),
    ),
    "test_runs": RetellAIEndpoint(
        path="/v2/list-test-runs/{id}",
        primary_key=("test_case_batch_job_id", "test_case_job_id"),
        sortable=False,
        parents=(RetellAIParent(table="batch_tests", id_field="test_case_batch_job_id"),),
        include_parent_id=True,
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "calls": [incremental_field("start_timestamp")],
    "chats": [incremental_field("start_timestamp")],
}
