from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.steam import SteamSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.steam.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PLAYTIME_SNAPSHOTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.steam.steam import (
    parse_steam_ids,
    probe_api_key,
    split_steam_ids,
    steam_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SteamSource(SimpleSource[SteamSourceConfig]):
    api_docs_url = "https://partner.steamgames.com/doc/webapi"

    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STEAM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.STEAM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            keywords=["games", "gaming", "playtime"],
            label="Steam",
            releaseStatus=ReleaseStatus.ALPHA,
            featureFlag="dwh-steam",
            caption=(
                "Sync the games and playtime of a list of Steam players.\n\n"
                "Create a key on the [Steam Web API key page](https://steamcommunity.com/dev/apikey). "
                "Each player's profile and game details must be public, or Steam returns no games for them.\n\n"
                "The tables identify each player by an opaque key. They hold no Steam ID, name, or location.\n\n"
                "Steam reports playtime totals, not sessions. Sync the `playtime_snapshots` table daily and "
                "subtract consecutive days to get the time played on each day."
            ),
            iconPath="/static/services/steam.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Steam Web API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="steam_ids",
                        label="Steam IDs",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="76561197960287930, 76561197960435530",
                        caption="The 17-digit Steam ID of each player, separated by commas or new lines.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.steam.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Steam Web API key is invalid. Create a new key, then update this source.",
            "403 Client Error": "Steam rejected your Web API key. Create a new key, then update this source.",
        }

    def get_schemas(
        self,
        config: SteamSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Merge only. A second sync on the same day must replace that day's snapshot, not add to it.
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=[PLAYTIME_SNAPSHOTS])

    def validate_credentials(
        self, config: SteamSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        try:
            parse_steam_ids(config.steam_ids)
        except ValueError as error:
            return False, str(error)
        status = probe_api_key(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Steam rejected this Web API key. Check the key and try again."
        return False, "Couldn't reach Steam to check the key. Try again in a moment."

    def source_for_pipeline(self, config: SteamSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Steam table: {inputs.schema_name}")
        return steam_source(
            api_key=config.api_key,
            team_id=inputs.team_id,
            # The credentials check validates the IDs. Steam returns nothing for an ID that is not one.
            steam_ids=split_steam_ids(config.steam_ids),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
