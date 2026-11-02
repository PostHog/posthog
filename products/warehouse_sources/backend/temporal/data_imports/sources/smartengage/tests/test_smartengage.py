import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartengage import (
    SmartEngageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.smartengage import (
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.source import SmartEngageSource


def _driver() -> SourceDriver:
    return SourceDriver(SmartEngageSource(), SmartEngageSourceConfig(api_key="se_key"))


class TestSmartEngageTransport:
    @parameterized.expand(
        [
            ("server_error", 503, {}, (False, "SmartEngage API returned status 503")),
            # An error object served with a 200 must not validate as a working key.
            (
                "error_body_with_200",
                200,
                {"error": "invalid key"},
                (False, "SmartEngage API returned an unexpected response"),
            ),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name, status, payload, expected) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json=payload))):
            assert validate_credentials(api_key="se_key") == expected

    @parameterized.expand([("tags",), ("custom_fields",), ("sequences",)])
    def test_get_resource_rejects_fanout_endpoints(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(endpoint=endpoint)

    def test_avatars_source_response(self) -> None:
        result = _driver().run("avatars", [ScriptedResponse(json=[])])

        response = result.response
        assert response is not None
        assert response.name == "avatars"
        assert response.primary_keys == ["avatar_id"]
        # No SmartEngage table has a stable timestamp, so nothing is partitioned.
        assert response.partition_mode is None

    @parameterized.expand(
        [
            ("tags", "tag_id"),
            ("custom_fields", "custom_field_id"),
            ("sequences", "sequence_id"),
        ]
    )
    def test_fanout_row_format_and_composite_key(self, endpoint, child_id_field) -> None:
        def script(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/avatars/list"):
                return ScriptedResponse(json=[{"avatar_id": "av_1"}])
            return ScriptedResponse(json=[{child_id_field: "child_1"}])

        result = _driver().run(endpoint, script)

        assert result.rows == [{child_id_field: "child_1", "avatar_id": "av_1"}]
        assert result.params("avatar_id") == [None, "av_1"]
        # Child ids are only documented per avatar, so the avatar id must stay in the key —
        # dropping it seeds duplicate rows that every later merge multi-matches.
        assert result.response is not None
        assert result.response.primary_keys == ["avatar_id", child_id_field]
