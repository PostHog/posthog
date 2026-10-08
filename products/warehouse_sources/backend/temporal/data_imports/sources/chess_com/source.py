from datetime import datetime
from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chess_com.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chess_com.chess_com import (
    chess_com_source,
    parse_usernames,
    probe_username,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chess_com.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chesscom import (
    ChessComSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChessComSource(SimpleSource[ChessComSourceConfig]):
    api_docs_url = "https://www.chess.com/news/view/published-data-api"

    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHESSCOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CHESSCOM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            keywords=["chess", "games", "gaming"],
            label="Chess.com",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Sync the games and ratings of a list of Chess.com players.\n\n"
                "Chess.com publishes this data without a key. "
                "The tables identify each player by an opaque key. They hold no username, game link, or moves.\n\n"
                "After you add a username, resync the `games` table to load that player's earlier games."
            ),
            iconPath="/static/services/chess-com.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="usernames",
                        label="Chess.com usernames",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="hikaru, magnuscarlsen",
                        caption="The username of each player, separated by commas or new lines.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "403 Client Error": "Chess.com refused the request. Wait a while, then sync again.",
            "410 Client Error": "Chess.com no longer serves this data.",
            "Not a Chess.com username": "One of the usernames is not valid. Fix the list, then sync again.",
            "Add at most": "The list has too many usernames. Shorten it, then sync again.",
        }

    def get_schemas(
        self,
        config: ChessComSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ChessComSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            usernames = parse_usernames(config.usernames)
        except ValueError as error:
            return False, str(error)
        for username in usernames:
            status = probe_username(username)
            if status == 404:
                return False, f"Chess.com has no player named {username}. Check the spelling and try again."
            if status != 200:
                return False, "Couldn't reach Chess.com to check the usernames. Try again in a moment."
        return True, None

    def source_for_pipeline(self, config: ChessComSourceConfig, inputs: SourceInputs) -> SourceResponse:
        if inputs.schema_name not in ENDPOINTS:
            raise ValueError(f"Unknown Chess.com table: {inputs.schema_name}")
        last_value = inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None
        return chess_com_source(
            team_id=inputs.team_id,
            usernames=parse_usernames(config.usernames),
            endpoint=inputs.schema_name,
            since=last_value if isinstance(last_value, datetime) else None,
            logger=inputs.logger,
        )
