from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "players": {
        "description": "One row for each Steam player listed on the source.",
        "columns": {
            "player_key": "Opaque key of the player. The Steam ID is not stored.",
            "is_public": "Whether the profile is public. Steam returns no games for a profile that is not.",
        },
    },
    "owned_games": {
        "description": "One row for each game a listed player owns or played for free.",
        "columns": {
            "player_key": "Opaque key of the player. The Steam ID is not stored.",
            "app_id": "Steam application ID of the game.",
            "name": "Name of the game.",
            "playtime_forever_minutes": "Total minutes the player has played the game.",
            "playtime_2weeks_minutes": "Minutes the player played the game in the last two weeks.",
            "last_played_at": "Date and time the player last played the game.",
        },
    },
    "playtime_snapshots": {
        "description": (
            "One row per player, game and day for each game played in the last two weeks. "
            "Subtract the total of the previous day to get the minutes played on a day."
        ),
        "columns": {
            "player_key": "Opaque key of the player. The Steam ID is not stored.",
            "app_id": "Steam application ID of the game.",
            "name": "Name of the game.",
            "snapshot_date": "UTC date the totals were read.",
            "playtime_forever_minutes": "Total minutes the player had played the game on that date.",
            "playtime_2weeks_minutes": "Minutes the player played the game in the two weeks before that date.",
        },
    },
}
