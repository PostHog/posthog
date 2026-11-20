# Bots whose handle does not carry GitHub's automatic ``[bot]`` suffix.
KNOWN_BOT_HANDLES: frozenset[str] = frozenset(
    {
        "posthog-bot",
        "dependabot",
        "renovate",
        "github-actions",
    }
)


def _bot_handle_in_list() -> str:
    # The handles are inlined as SQL literals, so this set must never hold user input.
    return ", ".join(f"'{handle}'" for handle in sorted(KNOWN_BOT_HANDLES))


def bot_handle_expr(handle_column: str) -> str:
    return f"({handle_column} LIKE '%[bot]' OR {handle_column} IN ({_bot_handle_in_list()}))"
