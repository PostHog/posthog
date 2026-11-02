from collections.abc import Iterable

import pytest
from unittest.mock import Mock

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.poplar import PoplarSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.poplar.settings import BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.poplar.source import PoplarSource


@pytest.mark.parametrize(
    "status,reason,path",
    [
        (401, "Unauthorized", "campaigns"),
        (403, "Forbidden", "campaigns"),
        (403, "Forbidden", "campaign/camp-1/mailings"),
    ],
)
def test_rejected_token_during_sync_is_not_retried_and_names_the_production_token(
    status: int, reason: str, path: str
) -> None:
    source = PoplarSource()
    inputs = SourceInputs(
        schema_name="campaign_mailings",
        schema_id="schema",
        source_id="source",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job",
        logger=Mock(),
        reset_pipeline=False,
    )
    with requests_mock.Mocker() as http:
        http.get(f"{BASE_URL}/campaigns", json=[{"id": "camp-1", "name": "Welcome postcards"}])
        http.get(f"{BASE_URL}/{path}", status_code=status, reason=reason, json={"error": "Unauthorized"})
        response = source.source_for_pipeline(
            PoplarSourceConfig(access_token="fake-token"), Mock(can_resume=Mock(return_value=False)), inputs
        )
        items = response.items()
        assert isinstance(items, Iterable)
        with pytest.raises(HTTPError) as error:
            list(items)
        assert http.call_count == (1 if path == "campaigns" else 2)
    messages = [
        message for pattern, message in source.get_non_retryable_errors().items() if pattern in str(error.value)
    ]
    assert len(messages) == 1
    assert messages[0] is not None and "production token" in messages[0]
