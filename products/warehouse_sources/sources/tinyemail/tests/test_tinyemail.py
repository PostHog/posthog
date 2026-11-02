from typing import Any, cast

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.tinyemail import (
    TinyemailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.source import TinyemailSource
from products.warehouse_sources.backend.temporal.data_imports.sources.tinyemail.tinyemail import (
    get_resource,
    validate_credentials,
)


def _members_walk(request: RecordedRequest) -> ScriptedResponse:
    if request.path.endswith("/contacts"):
        return ScriptedResponse(json={"contacts": [{"id": "list_1", "name": "Newsletter"}]})
    if request.param("page") == "1":
        return ScriptedResponse(json={"members": {"content": [{"email": "a@example.com"}]}})
    return ScriptedResponse(json={"members": {"content": []}})


class TestTinyemailTransport:
    @parameterized.expand(
        [
            # The campaigns list path really is singular, rows wrapped in `campaigns.content`,
            # and pages are 0-indexed.
            ("campaigns", "/campaign", "campaigns.content", PageNumberPaginator, 0, 20),
            ("contacts", "/contacts", "contacts", SinglePagePaginator, None, None),
            ("sender_details", "/sender-details", "senderDetailses", SinglePagePaginator, None, None),
        ]
    )
    def test_get_resource_top_level(self, endpoint, path, data_selector, paginator_type, base_page, size) -> None:
        resource = cast(dict[str, Any], get_resource(endpoint))

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"
        assert resource["endpoint"]["path"] == path
        assert resource["endpoint"]["data_selector"] == data_selector

        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, paginator_type)
        if base_page is not None:
            assert paginator.page == base_page
        if size is not None:
            assert resource["endpoint"]["params"]["size"] == size
        else:
            assert "size" not in resource["endpoint"]["params"]

    def test_get_resource_rejects_fanout_endpoint(self) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource("contact_members")

    def test_tinyemail_source_top_level_response(self) -> None:
        driver = SourceDriver(TinyemailSource(), TinyemailSourceConfig(api_key="key"))
        result = driver.run("campaigns", always(ScriptedResponse(json={"campaigns": {"content": []}})))

        assert result.response is not None
        assert result.response.name == "campaigns"
        assert result.response.primary_keys == ["id"]

    def test_tinyemail_source_contact_members_row_format(self) -> None:
        driver = SourceDriver(TinyemailSource(), TinyemailSourceConfig(api_key="key"))
        result = driver.run("contact_members", _members_walk)

        assert result.raised is None
        assert result.rows == [{"email": "a@example.com", "contact_id": "list_1"}]
        # An email is only unique within one contact list, so the parent id is part of the key.
        assert result.response is not None
        assert result.response.primary_keys == ["contact_id", "email"]

    def test_validate_credentials_handles_request_exception(self) -> None:
        with scripted_network(always(ConnectionResetError("reset"))):
            is_valid, message = validate_credentials(api_key="key")

        assert is_valid is False
        assert message is not None and "Could not connect to the tinyEmail API" in message
