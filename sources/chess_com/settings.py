from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

GAMES = "games"
RATINGS = "ratings"

ENDPOINTS = (GAMES, RATINGS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    GAMES: [
        {
            "label": "end_time",
            "type": IncrementalFieldType.DateTime,
            "field": "end_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

# Each key includes the player, because every table holds rows from all listed players.
PRIMARY_KEYS: dict[str, list[str]] = {
    GAMES: ["player_key", "game_key"],
    RATINGS: ["player_key", "time_class"],
}
