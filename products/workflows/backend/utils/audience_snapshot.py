from datetime import timedelta

import posthoganalytics

from posthog.models.team.team import Team

AUDIENCE_SNAPSHOT_FLAG = "workflows-batch-audience-snapshot"

# A run waits this long for its audience to resolve, then fails. The query itself is capped well below it.
AUDIENCE_SNAPSHOT_WAIT_LIMIT = timedelta(hours=2)


def use_audience_snapshot(team: Team) -> bool:
    # A flag service error must not stop the run from being dispatched, so it falls back to the old path.
    try:
        return bool(
            posthoganalytics.feature_enabled(
                AUDIENCE_SNAPSHOT_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False
