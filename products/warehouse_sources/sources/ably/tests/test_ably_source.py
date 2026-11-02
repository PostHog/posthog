import pytest

from products.warehouse_sources.backend.facade.source_config import (
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ably.source import AblySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ably import AblySourceConfig


class TestAblySource:
    def setup_method(self):
        self.source = AblySource()
        self.team_id = 123

    def _field(self, name: str):
        return next(f for f in self.source.get_source_config.fields if f.name == name)

    def test_api_key_field_is_secret_password(self):
        field = self._field("api_key")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_unit_field_defaults_to_hour(self):
        field = self._field("unit")
        assert isinstance(field, SourceFieldSelectConfig)
        assert field.defaultValue == "hour"
        assert {option.value for option in field.options} == {"minute", "hour", "day", "month"}

    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, (True, None)),
            (401, (False, "Ably authentication failed. Please check your API key.")),
            (403, (False, "Ably authentication failed. Please check your API key.")),
        ],
    )
    def test_validate_credentials(self, status_code: int, expected: tuple[bool, str | None]) -> None:
        config = AblySourceConfig(api_key="app.key:secret", unit="hour")
        with scripted_network([ScriptedResponse(status=status_code)]):
            assert self.source.validate_credentials(config, self.team_id) == expected

    def test_validate_credentials_rejects_malformed_key(self):
        config = AblySourceConfig(api_key="no-colon-here", unit="hour")
        ok, error = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert error is not None and "malformed" in error.lower()

    @pytest.mark.parametrize(
        ("schema_name", "primary_keys", "partition_keys"),
        [
            ("Stats", ["unit", "intervalId"], ["interval_start"]),
            ("Channels", ["channelId"], None),
            # The channel-scoped tables aggregate rows from every channel, so the channel has to
            # be part of the key; a bare `id` would multi-match on merge.
            ("ChannelMessages", ["channel_id", "id"], ["message_time"]),
            ("Presence", ["channel_id", "id"], None),
        ],
    )
    def test_source_for_pipeline_shapes_the_response_per_schema(
        self, schema_name: str, primary_keys: list[str], partition_keys: list[str] | None
    ) -> None:
        config = AblySourceConfig(api_key="app.key:secret", unit="day")
        result = SourceDriver(self.source, config).run(schema_name, [ScriptedResponse(json=[])], api_version="2")
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.name == schema_name
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize(
        ("pinned", "resolved"),
        [
            # No pin falls back to default_version ("2"); an explicit pin is honored verbatim,
            # including the legacy label so a deprecated source keeps its own request path.
            (None, "2"),
            ("v1", "v1"),
            ("2", "2"),
        ],
    )
    def test_source_for_pipeline_resolves_and_threads_api_version(self, pinned: str | None, resolved: str) -> None:
        config = AblySourceConfig(api_key="app.key:secret", unit="hour")
        result = SourceDriver(self.source, config).run("Stats", [ScriptedResponse(json=[])], api_version=pinned)

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.requests[0].headers.get("x-ably-version") == (resolved if resolved == "2" else None)

    def test_source_for_pipeline_ignores_last_value_on_full_refresh(self):
        config = AblySourceConfig(api_key="app.key:secret", unit="hour")
        result = SourceDriver(self.source, config).run(
            "Stats",
            [ScriptedResponse(json=[])],
            should_use_incremental_field=False,
            db_incremental_field_last_value=1700000000000,
        )

        assert result.raised is None
        assert result.requests[0].param("start") is None
        assert result.requests[0].param("end") is None
