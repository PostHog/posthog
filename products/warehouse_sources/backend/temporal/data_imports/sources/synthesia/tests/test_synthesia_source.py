from urllib.parse import urlsplit

import pytest
from unittest.mock import patch

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.synthesia import (
    SynthesiaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.source import SynthesiaSource


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
