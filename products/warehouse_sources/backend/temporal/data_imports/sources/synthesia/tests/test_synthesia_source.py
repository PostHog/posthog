from urllib.parse import urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.synthesia import (
    SynthesiaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.source import SynthesiaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.synthesia import SynthesiaResumeConfig


@pytest.mark.parametrize("schema_name", [None, "templates", "webhooks"])
def test_credential_probe_uses_selected_endpoint(schema_name: str | None) -> None:
    response = Response()
    response.status_code = 200
    response._content = b"{}"
    with patch("requests.Session.send", return_value=response) as send:
        result = SynthesiaSource().validate_credentials(
            SynthesiaSourceConfig(api_key="fake-api-key"), team_id=1, schema_name=schema_name
        )
    assert result == (True, None)
    assert urlsplit(send.call_args.args[0].url).path == f"/v2/{schema_name or 'videos'}"


def test_resumable_source_manager_uses_synthesia_checkpoint() -> None:
    manager = SynthesiaSource().get_resumable_source_manager(MagicMock())

    assert isinstance(manager, ResumableSourceManager)
    assert manager._data_class is SynthesiaResumeConfig


def test_source_for_pipeline_plumbs_sync_context() -> None:
    config = SynthesiaSourceConfig(api_key="fake-api-key")
    inputs = MagicMock(schema_name="templates", team_id=2, job_id="job-id", api_version=None)
    manager = MagicMock(spec=ResumableSourceManager)
    response = MagicMock()

    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.source.synthesia_source",
        return_value=response,
    ) as source:
        result = SynthesiaSource().source_for_pipeline(config, manager, inputs)

    assert result is response
    source.assert_called_once_with(
        api_key="fake-api-key",
        api_version="v2",
        endpoint="templates",
        team_id=2,
        job_id="job-id",
        resumable_source_manager=manager,
    )
