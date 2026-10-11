from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.spotify_ads._config import SpotifyAdsSourceConfig


@SourceRegistry.register
class SpotifyAdsSource(SimpleSource[SpotifyAdsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPOTIFYADS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SPOTIFYADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Spotify Ads",
            iconPath="/static/services/spotify_ads.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
