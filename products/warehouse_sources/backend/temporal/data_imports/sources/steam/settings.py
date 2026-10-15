from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PLAYERS = "players"
OWNED_GAMES = "owned_games"
PLAYTIME_SNAPSHOTS = "playtime_snapshots"

ENDPOINTS = (PLAYERS, OWNED_GAMES, PLAYTIME_SNAPSHOTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    PLAYTIME_SNAPSHOTS: [
        {
            "label": "snapshot_date",
            "type": IncrementalFieldType.Date,
            "field": "snapshot_date",
            "field_type": IncrementalFieldType.Date,
        }
    ],
}

# Each key includes the player, because every table holds rows from all listed players.
PRIMARY_KEYS: dict[str, list[str]] = {
    PLAYERS: ["player_key"],
    OWNED_GAMES: ["player_key", "app_id"],
    PLAYTIME_SNAPSHOTS: ["player_key", "app_id", "snapshot_date"],
}
