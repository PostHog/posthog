import re
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sanity import SanitySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sanity.settings import (
    PAGE_SIZE,
    SanityEndpoint,
    document_endpoint,
)


@frozen
class SanityResumeConfig:
    last_id: str
    last_updated_at: str | None = None


class SanityClient:
    def __init__(self, config: SanitySourceConfig, api_version: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*", config.project_id):
            raise ValueError("Enter a Sanity project ID with letters, numbers, or hyphens.")
        if not re.fullmatch(r"~?[a-z0-9][a-z0-9_-]{0,63}", config.dataset):
            raise ValueError("Enter a Sanity dataset name with lowercase letters, numbers, underscores, or hyphens.")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", api_version):
            raise ValueError("Enter a Sanity API version in YYYY-MM-DD format.")
        if not config.api_token.strip():
            raise ValueError("Enter a Sanity API token with read access to the dataset.")

        self.url = f"https://{config.project_id}.api.sanity.io/v{api_version}/data/query/{config.dataset}"
        self.session = make_tracked_session(
            headers={"Authorization": f"Bearer {config.api_token}"},
            redact_values=(config.api_token,),
            allow_redirects=False,
        )

    def query(self, query: str, parameters: dict[str, str] | None = None) -> object:
        params = {"query": query, "perspective": "raw"}
        params.update({f"${key}": json.dumps(value) for key, value in (parameters or {}).items()})
        response = self.session.get(self.url, params=params, timeout=(10, 70))
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or "result" not in body:
            raise ValueError("Sanity returned an invalid query response. Try the sync again.")
        return body["result"]

    def close(self) -> None:
        self.session.close()


def _format_watermark(value: object) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("The Sanity incremental value must be a timestamp.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def get_rows(
    config: SanitySourceConfig,
    endpoint: SanityEndpoint,
    manager: ResumableSourceManager[SanityResumeConfig],
    inputs: SourceInputs,
    api_version: str,
) -> Iterator[list[dict[str, object]]]:
    client = SanityClient(config, api_version)
    try:
        resume = manager.load_state() if manager.can_resume() else None
        filters = ["_type == $type"]
        parameters = {"type": endpoint.document_type}
        incremental = inputs.should_use_incremental_field
        if incremental and inputs.incremental_field not in (None, endpoint.incremental_field):
            raise ValueError("Sanity incremental sync requires the _updatedAt field.")
        if incremental and inputs.db_incremental_field_last_value is not None:
            # GROQ filters run on the server. This filter has no live-account verification.
            filters.append("_updatedAt >= $since")
            parameters["since"] = _format_watermark(inputs.db_incremental_field_last_value)

        while True:
            page_filters = list(filters)
            if resume is not None:
                parameters["lastId"] = resume.last_id
                if incremental:
                    if resume.last_updated_at is None:
                        raise ValueError("The Sanity resume cursor has no update timestamp. Restart the sync.")
                    parameters["lastUpdatedAt"] = resume.last_updated_at
                    page_filters.append(
                        "(_updatedAt > $lastUpdatedAt || (_updatedAt == $lastUpdatedAt && _id > $lastId))"
                    )
                else:
                    page_filters.append("_id > $lastId")

            order = "_updatedAt asc, _id asc" if incremental else "_id asc"
            # GROQ embeds the cursor filter in the query, so standard REST paginators cannot advance it.
            query = f"*[{' && '.join(page_filters)}] | order({order}) [0...{PAGE_SIZE}]"
            result = client.query(query, parameters)
            if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
                raise ValueError("Sanity returned an invalid document list. Try the sync again.")
            if not result:
                manager.safe_point()
                return

            rows = cast(list[dict[str, object]], result)
            last_id = rows[-1].get("_id")
            last_updated_at = rows[-1].get("_updatedAt") if incremental else None
            if not isinstance(last_id, str) or (incremental and not isinstance(last_updated_at, str)):
                raise ValueError("Sanity returned a document without a sync cursor. Try the sync again.")
            next_resume = SanityResumeConfig(last_id=last_id, last_updated_at=cast(str | None, last_updated_at))
            if next_resume == resume:
                raise ValueError("Sanity did not advance the sync cursor. Restart the sync.")
            manager.save_state(next_resume)
            yield rows
            manager.safe_point()
            resume = next_resume
            if len(rows) < PAGE_SIZE:
                return
    finally:
        client.close()


def sanity_source(
    config: SanitySourceConfig,
    manager: ResumableSourceManager[SanityResumeConfig],
    inputs: SourceInputs,
    api_version: str,
) -> SourceResponse:
    endpoint = document_endpoint(inputs.schema_name)
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: get_rows(config, endpoint, manager, inputs, api_version),
        primary_keys=list(endpoint.primary_keys),
        sort_mode="asc",
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        partition_count=1,
        partition_size=1,
        chunk_size_bytes=20 * 1024 * 1024,
    )
