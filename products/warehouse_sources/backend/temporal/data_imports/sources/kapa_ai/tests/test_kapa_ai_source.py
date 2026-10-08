import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kapaai import KapaAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.source import KapaAISource


@pytest.mark.parametrize("status,reason", [(401, "Unauthorized"), (403, "Forbidden")])
def test_pipeline_auth_failures_match_terminal_errors(status: int, reason: str) -> None:
    source = KapaAISource()
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    inputs = MagicMock(spec=SourceInputs, schema_name="threads", team_id=1, job_id="test-job")
    config = KapaAISourceConfig(api_key="test-key", project_id="00000000-0000-4000-8000-000000000001")
    response = Response()
    response.status_code = status
    response.reason = reason
    response.url = "https://api.kapa.ai/query/v1/projects/00000000-0000-4000-8000-000000000001/threads/"
    response._content = b"{}"
    with patch("requests.sessions.Session.send", return_value=response) as send:
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], source.source_for_pipeline(config, manager, inputs).items()))
    assert send.call_count == 1
    assert error_message_matches(str(error.value), source.get_non_retryable_errors())


def test_unknown_table_is_rejected_before_fetching() -> None:
    config = KapaAISourceConfig(api_key="test-key", project_id="00000000-0000-4000-8000-000000000001")
    inputs = MagicMock(spec=SourceInputs, schema_name="missing", team_id=1, job_id="test-job")
    with pytest.raises(UnknownResourceError, match="missing"):
        KapaAISource().source_for_pipeline(config, MagicMock(spec=ResumableSourceManager), inputs)


def test_full_refresh_ignores_a_stale_watermark() -> None:
    config = KapaAISourceConfig(api_key="test-key", project_id="00000000-0000-4000-8000-000000000001")
    inputs = MagicMock(
        spec=SourceInputs,
        schema_name="threads",
        team_id=1,
        job_id="test-job",
        should_use_incremental_field=False,
        db_incremental_field_last_value="2025-01-01T00:00:00Z",
    )
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    response = Response()
    response.status_code = 200
    response._content = json.dumps(
        {"results": [{"id": "old-thread", "last_activity_at": None}], "next_cursor": None}
    ).encode()
    with patch("requests.sessions.Session.send", return_value=response) as send:
        result = KapaAISource().source_for_pipeline(config, manager, inputs)
        assert list(cast(Iterable[Any], result.items())) == [[{"id": "old-thread", "last_activity_at": None}]]
    assert "updated_since" not in send.call_args.args[0].url
