from posthog.dags.common import JobOwners
from posthog.dags.daily_rollups import build_daily_rollup_definitions

from products.growth.backend.sdk_version_rollup import SdkVersionsDailyRollup

sdk_versions_daily_rollup = build_daily_rollup_definitions(SdkVersionsDailyRollup, owner=JobOwners.TEAM_GROWTH)
