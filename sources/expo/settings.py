from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

_BUILD_FIELDS = """
    id
    status
    platform
    distribution
    buildProfile
    appIdentifier
    sdkVersion
    appVersion
    appBuildVersion
    gitCommitHash
    gitCommitMessage
    message
    priority
    createdAt
    updatedAt
    completedAt
    expirationDate
    isForIosSimulator
    error {
      errorCode
      message
    }
    artifacts {
      buildUrl
      applicationArchiveUrl
      buildArtifactsUrl
    }
    initiatingActor {
      id
      displayName
    }
    updateChannel {
      id
      name
    }
    runtime {
      id
      version
    }
    metrics {
      buildWaitTime
      buildQueueTime
      buildDuration
    }
"""

_SUBMISSION_FIELDS = """
    id
    status
    platform
    androidConfig {
      track
      releaseStatus
      rollout
    }
    iosConfig {
      ascAppIdentifier
      appleIdUsername
    }
    error {
      errorCode
      message
    }
"""


@frozen
class ExpoEndpointConfig:
    name: str
    # Field on `app.byId` that holds the collection, also the key the rows come back under.
    collection: str
    fields: str
    primary_key: str = "id"
    partition_key: Optional[str] = None


EXPO_ENDPOINTS: dict[str, ExpoEndpointConfig] = {
    "builds": ExpoEndpointConfig(
        name="builds",
        collection="builds",
        fields=_BUILD_FIELDS,
        partition_key="createdAt",
    ),
    "submissions": ExpoEndpointConfig(
        name="submissions",
        collection="submissions",
        fields=_SUBMISSION_FIELDS,
    ),
}

ENDPOINTS = tuple(EXPO_ENDPOINTS.keys())

# EAS paginates these collections by offset with no documented date filter, so both tables are a
# full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}


def build_query(endpoint: str) -> str:
    config = EXPO_ENDPOINTS[endpoint]
    collection_arguments = (
        "filter: {}, offset: $offset, limit: $limit" if endpoint == "submissions" else "offset: $offset, limit: $limit"
    )
    return f"""
query PostHogExpo{config.collection.title()}($appId: String!, $offset: Int!, $limit: Int!) {{
  app {{
    byId(appId: $appId) {{
      id
      {config.collection}({collection_arguments}) {{
{config.fields}
      }}
    }}
  }}
}}
"""
