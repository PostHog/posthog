from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "player_achievements": {
        "description": (
            "One row per player, game and achievement for each played game that has achievements. "
            "Locked achievements are included with achieved set to false."
        ),
        "docs_url": "https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetPlayerAchievements",
        "columns": {
            "player_key": "Opaque key of the player. The Steam ID is not stored.",
            "app_id": "Steam application ID of the game.",
            "api_name": "API name of the achievement, unique within the game.",
            "name": "Display name of the achievement, in English.",
            "description": "Description of the achievement, in English.",
            "achieved": "Whether the player has unlocked the achievement.",
            "unlocked_at": "Date and time the player unlocked the achievement. Empty when it is locked.",
        },
    },
    "friends": {
        "description": "One row for each friend of a listed player whose friend list is public.",
        "docs_url": "https://partner.steamgames.com/doc/webapi/ISteamUser#GetFriendList",
        "columns": {
            "player_key": "Opaque key of the player. The Steam ID is not stored.",
            "friend_key": (
                "Opaque key of the friend, made the same way as player_key. "
                "It matches player_key when the friend is also a listed player."
            ),
            "relationship": "Relationship between the two accounts. Always friend.",
            "friend_since": "Date and time the two players became friends.",
        },
    },
    "current_players": {
        "description": (
            "Number of players in each game that a listed player owns, read at each sync. "
            "Each sync adds one row per game, so the rows over time are a history of concurrent players."
        ),
        "docs_url": "https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers",
        "columns": {
            "app_id": "Steam application ID of the game.",
            "player_count": "Number of players in the game at that time. Players not connected to Steam are not counted.",
            "captured_at": "UTC date and time the count was read.",
        },
    },
    "global_achievement_percentages": {
        "description": (
            "Percentage of the game's players who unlocked each achievement, "
            "for each game with achievements that a listed player owns."
        ),
        "docs_url": "https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetGlobalAchievementPercentagesForApp",
        "columns": {
            "app_id": "Steam application ID of the game.",
            "api_name": "API name of the achievement. It matches api_name in player_achievements.",
            "percent": "Percentage of the game's players who unlocked the achievement, from 0 to 100.",
        },
    },
}
