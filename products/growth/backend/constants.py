SDK_CACHE_EXPIRY = 60 * 60 * 24 * 7  # 7 days


def github_sdk_versions_key(sdk_type: str) -> str:
    return f"github:sdk_versions:{sdk_type}"


def team_sdk_versions_key(team_id: int) -> str:
    return f"sdk_versions:team:{team_id}"
