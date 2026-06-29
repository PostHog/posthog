from dataclasses import dataclass, field


@dataclass
class GainsightPxEndpointConfig:
    name: str
    path: str
    # JSON key under which the list endpoint nests its records — it varies per endpoint in PX
    # (`/accounts` returns `{"accounts": [...]}`, `/feature` returns `{"features": [...]}`, etc.).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Endpoint catalog mirrors the streams the production open-source Airbyte Gainsight PX connector
# exposes (path, record key, primary key), cross-checked against https://px-apidocs.gainsight.com.
# Every list endpoint is full-refresh: PX exposes no server-side modified-since filter on these
# entity resources, so there's no reliable incremental cursor (matching Airbyte, which ships the
# connector full-refresh only). Re-pulled rows dedupe on the `id` primary key.
GAINSIGHT_PX_ENDPOINTS: dict[str, GainsightPxEndpointConfig] = {
    "accounts": GainsightPxEndpointConfig(name="accounts", path="/accounts", data_key="accounts"),
    "users": GainsightPxEndpointConfig(name="users", path="/users", data_key="users"),
    # The PX segments resource is singular in the path even though it returns a `segments` list.
    "segments": GainsightPxEndpointConfig(name="segments", path="/segment", data_key="segments"),
    "features": GainsightPxEndpointConfig(name="features", path="/feature", data_key="features"),
    "articles": GainsightPxEndpointConfig(name="articles", path="/articles", data_key="articleExternalViewList"),
    "kcbots": GainsightPxEndpointConfig(name="kcbots", path="/kcbot", data_key="kcList"),
}

ENDPOINTS = tuple(GAINSIGHT_PX_ENDPOINTS.keys())
