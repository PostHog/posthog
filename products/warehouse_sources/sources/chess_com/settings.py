from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

GAMES = "games"
RATINGS = "ratings"
PLAYERS = "players"
TOURNAMENTS = "tournaments"
TEAM_MATCHES = "team_matches"
LEADERBOARDS = "leaderboards"

ENDPOINTS = (GAMES, RATINGS, PLAYERS, TOURNAMENTS, TEAM_MATCHES, LEADERBOARDS)

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

# Each key includes the player, because every table holds rows from many players.
PRIMARY_KEYS: dict[str, list[str]] = {
    GAMES: ["player_key", "game_key"],
    RATINGS: ["player_key", "time_class"],
    PLAYERS: ["player_key"],
    TOURNAMENTS: ["player_key", "tournament_key"],
    TEAM_MATCHES: ["player_key", "match_key"],
    LEADERBOARDS: ["leaderboard", "player_key"],
}
