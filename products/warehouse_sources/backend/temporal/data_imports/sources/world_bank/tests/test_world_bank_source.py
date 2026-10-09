import json
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import structlog
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.worldbank import (
    WorldBankSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.settings import PRIMARY_KEYS
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.source import WorldBankSource
from products.warehouse_sources.backend.temporal.data_imports.sources.world_bank.world_bank import (
    MAX_INDICATOR_CODES,
    world_bank_source,
)


def _make_inputs(schema_name: str = "countries") -> SourceInputs:
    return SourceInputs(
        schema_name=schema_name,
        schema_id="schema-id",
        source_id="source-id",
        team_id=123,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job-id",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestWorldBankSource:
    def setup_method(self) -> None:
        self.source = WorldBankSource()
        self.config = WorldBankSourceConfig(indicator_codes="SP.POP.TOTL\nNY.GDP.PCAP.CD")

    def test_indicator_data_primary_key_is_unique_table_wide(self) -> None:
        # One table holds observations for every configured indicator, so the indicator has to be
        # part of the key or codes would overwrite each other.
        assert PRIMARY_KEYS["indicator_data"] == ["indicator_id", "country_id", "date"]

    def test_non_retryable_error_matches_an_out_of_bounds_code_list(self) -> None:
        # Retrying an oversized code list just burns the same capacity again, so the sync has to
        # fail immediately. The raised text and the matched pattern must stay in step.
        with pytest.raises(ValueError) as excinfo:
            list(
                world_bank_source(
                    endpoint="indicator_data",
                    indicator_codes=[f"CODE.{index}" for index in range(MAX_INDICATOR_CODES + 1)],
                    api_version="v2",
                    team_id=123,
                    job_id="job-id",
                    resumable_source_manager=MagicMock(spec=ResumableSourceManager),
                )
            )

        assert error_message_matches(str(excinfo.value), self.source.get_non_retryable_errors().keys())

    def test_a_mid_sync_failure_never_resumes_past_an_unflushed_page(self) -> None:
        # The resume checkpoint advances after every yielded page, but pages sit in the batcher's
        # buffer until it flushes. If the checkpoint could move past a buffered page, a failed
        # request would resume beyond rows that were never written and finish the full-refresh
        # table with silent gaps. Drive the real batcher at the source's declared chunk size and
        # fail the third request: pages one and two must be durable and the last saved checkpoint
        # must point at exactly the page that failed.
        rest_client = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client"

        def _page(rows: list[dict[str, Any]], page: int) -> Response:
            response = Response()
            response.status_code = 200
            response._content = json.dumps([{"page": page, "pages": 3, "per_page": "1000", "total": 3}, rows]).encode()
            response.headers["Content-Type"] = "application/json"
            response.url = "https://api.worldbank.org/v2/country"
            return response

        responses: list[Any] = [_page([{"id": "ABW"}], 1), _page([{"id": "AFG"}], 2), RuntimeError("network dropped")]
        response_iter = iter(responses)

        def fake_send(request: Any, *_args: Any, **_kwargs: Any) -> Response:
            result = next(response_iter)
            if isinstance(result, Exception):
                raise result
            return result

        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False

        response = self.source.source_for_pipeline(self.config, manager, _make_inputs("countries"))
        # Each yielded item is a whole API page, so one page per batcher chunk is what keeps a page
        # durable before its checkpoint advances.
        assert response.chunk_size == 1

        batcher = Batcher(structlog.get_logger(), chunk_size=response.chunk_size)
        durable_pages: list[Any] = []
        durable_count_at_checkpoint: list[int] = []
        manager.save_state.side_effect = lambda _state: durable_count_at_checkpoint.append(len(durable_pages))

        with patch(f"{rest_client}.make_tracked_session") as MockSession:
            session = MockSession.return_value
            session.headers = {}
            session.prepare_request.side_effect = lambda request: request
            session.send.side_effect = fake_send

            with pytest.raises(RuntimeError, match="network dropped"):
                for page in cast(Iterable[Any], response.items()):
                    batcher.batch(page)
                    while batcher.should_yield():
                        durable_pages.append(batcher.get_table())

        # Every checkpoint was saved only after that many pages had been flushed durably, and the
        # last one resumes from page 3 — the request that failed — so nothing durable is skipped.
        assert durable_count_at_checkpoint == [1, 2]
        assert [call.args[0].page for call in manager.save_state.call_args_list] == [2, 3]
        assert len(durable_pages) == 2
