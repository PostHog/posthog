from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
            "pgn": (
                "Moves and clock times of the game in PGN. "
                "Player names are ?, and the tags that name a player or link to the game are removed."
            ),
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
    "players": {
        "description": "One row for each listed Chess.com player, with the public profile.",
        "columns": {
            "player_key": "Opaque key of the player. The username is not stored.",
            "title": "Chess title of the player, such as GM or IM, when the player has one.",
            "status": "Account status, such as basic, premium, closed or closed:fair_play_violations.",
            "country": "Two-letter code of the player's country. XX is an international or unknown country.",
            "joined_at": "Date and time the player registered on Chess.com.",
            "last_online_at": "Date and time the player last logged in.",
            "followers": "Number of players who follow the player.",
            "league": "Chess.com league of the player, such as Legend.",
            "fide_rating": "FIDE rating the player shows on the profile.",
            "is_streamer": "Whether the player is a Chess.com streamer.",
            "verified": "Whether Chess.com verified the account.",
        },
    },
    "tournaments": {
        "description": "One row per listed player and tournament the player finished, plays in or registered for.",
        "columns": {
            "player_key": "Opaque key of the player. The username is not stored.",
            "tournament_key": "Opaque key of the tournament. The tournament URL is not stored.",
            "state": "Where the tournament is for the player: finished, in_progress or registered.",
            "status": "Status of the player in the tournament, such as winner, eliminated, withdrew or registered.",
            "type": "Format of the tournament, such as swiss or arena.",
            "time_class": "Speed of the games: daily, rapid, blitz or bullet.",
            "wins": "Number of games the player won. Only for finished tournaments.",
            "losses": "Number of games the player lost. Only for finished tournaments.",
            "draws": "Number of games the player drew. Only for finished tournaments.",
            "points_awarded": "Points the player received. Only for finished tournaments.",
            "placement": "Final place of the player. Only for finished tournaments.",
            "total_players": "Number of players in the tournament. Only for finished tournaments.",
        },
    },
    "team_matches": {
        "description": "One row per listed player and club team match the player finished, plays in or registered for.",
        "columns": {
            "player_key": "Opaque key of the player. The username is not stored.",
            "match_key": "Opaque key of the team match. The match URL is not stored.",
            "club_key": "Opaque key of the club the player plays for. The club URL is not stored.",
            "state": "Where the match is for the player: finished, in_progress or registered.",
            "result_as_white": "Chess.com result code of the player's game with white, such as win, resigned or agreed.",
            "result_as_black": "Chess.com result code of the player's game with black, such as win, resigned or agreed.",
            "outcome_as_white": "Result of the player's game with white: win, draw or loss.",
            "outcome_as_black": "Result of the player's game with black: win, draw or loss.",
        },
    },
    "leaderboards": {
        "description": "One row per Chess.com leaderboard and top-50 player, as of the last sync.",
        "columns": {
            "leaderboard": "Name of the leaderboard, such as daily, live_blitz, tactics or rush.",
            "player_key": (
                "Opaque key of the player. The username is not stored. "
                "A listed player has the same key as in the other tables."
            ),
            "rank": "Place of the player on the leaderboard, from 1 to 50.",
            "score": "Score of the player on the leaderboard, such as the rating.",
            "title": "Chess title of the player, such as GM or IM, when the player has one.",
            "status": "Account status, such as basic or premium.",
            "country": "Two-letter code of the player's country. XX is an international or unknown country.",
            "wins": "Number of games the player won.",
            "losses": "Number of games the player lost.",
            "draws": "Number of games the player drew.",
            "score_trend_direction": "Direction of the latest score change: 1 for up, -1 for down, 0 for no change.",
            "score_trend_delta": "Size of the latest score change.",
            "rank_trend_direction": "Direction of the latest rank change: 1 for up, -1 for down, 0 for no change.",
            "rank_trend_delta": "Size of the latest rank change.",
        },
    },
}
