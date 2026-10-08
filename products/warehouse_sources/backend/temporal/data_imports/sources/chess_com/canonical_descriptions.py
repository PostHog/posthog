from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "games": {
        "description": "One row for each finished game of a listed Chess.com player.",
        "columns": {
            "player_key": "Opaque key of the player. The username is not stored.",
            "game_key": "Opaque key of the game. The game URL is not stored.",
            "end_time": "Date and time the game ended.",
            "time_class": "Speed of the game: daily, rapid, blitz or bullet.",
            "time_control": "Time control in PGN format, such as 600 or 180+2.",
            "rules": "Variant of the game. Standard chess is chess.",
            "rated": "Whether the game changed the players' ratings.",
            "color": "Color the player had: white or black.",
            "outcome": "Result for the player: win, draw or loss.",
            "result": "Chess.com result code for the player, such as win, checkmated, resigned or timeout.",
            "rating": "Rating of the player after the game.",
            "opponent_rating": "Rating of the opponent after the game.",
            "accuracy": "Accuracy score of the player, when Chess.com analyzed the game.",
        },
    },
    "ratings": {
        "description": "One row per listed player and game speed, with the current rating and record.",
        "columns": {
            "player_key": "Opaque key of the player. The username is not stored.",
            "time_class": "Speed of the games: daily, rapid, blitz or bullet.",
            "rating": "Current rating.",
            "best_rating": "Highest rating the player reached.",
            "wins": "Number of games won.",
            "losses": "Number of games lost.",
            "draws": "Number of games drawn.",
            "last_rated_at": "Date and time of the last rated game.",
        },
    },
}
