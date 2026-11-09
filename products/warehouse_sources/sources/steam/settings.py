from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

PLAYERS = "players"
OWNED_GAMES = "owned_games"
PLAYTIME_SNAPSHOTS = "playtime_snapshots"
PLAYER_ACHIEVEMENTS = "player_achievements"
FRIENDS = "friends"
CURRENT_PLAYERS = "current_players"
GLOBAL_ACHIEVEMENT_PERCENTAGES = "global_achievement_percentages"

ENDPOINTS = (
    PLAYERS,
    OWNED_GAMES,
    PLAYTIME_SNAPSHOTS,
    PLAYER_ACHIEVEMENTS,
    FRIENDS,
    CURRENT_PLAYERS,
    GLOBAL_ACHIEVEMENT_PERCENTAGES,
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    PLAYTIME_SNAPSHOTS: [
        {
            "label": "snapshot_date",
            "type": IncrementalFieldType.Date,
            "field": "snapshot_date",
            "field_type": IncrementalFieldType.Date,
        }
    ],
    CURRENT_PLAYERS: [
        {
            "label": "captured_at",
            "type": IncrementalFieldType.DateTime,
            "field": "captured_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}

# Each key includes the player, because every table holds rows from all listed players.
PRIMARY_KEYS: dict[str, list[str]] = {
    PLAYERS: ["player_key"],
    OWNED_GAMES: ["player_key", "app_id"],
    PLAYTIME_SNAPSHOTS: ["player_key", "app_id", "snapshot_date"],
    PLAYER_ACHIEVEMENTS: ["player_key", "app_id", "api_name"],
    FRIENDS: ["player_key", "friend_key"],
    CURRENT_PLAYERS: ["app_id", "captured_at"],
    GLOBAL_ACHIEVEMENT_PERCENTAGES: ["app_id", "api_name"],
}
