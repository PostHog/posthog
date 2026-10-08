# A leaf module: `prompt_questions` runs in web requests and must not load the temporal package to get this.
def replay_vision_distinct_id(team_id: int) -> str:
    """`posthog_distinct_id` for analytics events emitted by Replay Vision when no human user is attributable."""
    return f"replay-vision:{team_id}"
