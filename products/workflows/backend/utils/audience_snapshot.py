from datetime import timedelta

import posthoganalytics

from posthog.models.team.team import Team

AUDIENCE_SNAPSHOT_FLAG = "workflows-batch-audience-snapshot"

# A run waits this long for its audience to resolve, then fails. The query itself is capped well below it.
AUDIENCE_SNAPSHOT_WAIT_LIMIT = timedelta(hours=2)


def use_audience_snapshot(team: Team) -> bool:
    return bool(
        posthoganalytics.feature_enabled(
            AUDIENCE_SNAPSHOT_FLAG,
            str(team.uuid),
            send_feature_flag_events=False,
        )
    )
