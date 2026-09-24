import { useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { recordingLikelyExpired, recordingRetentionDays } from '../utils/recordingRetention'

/** Renders nothing while the observed session's recording is still within retention. */
export function RecordingExpiredTag({ observation }: { observation: ReplayObservationApi }): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const period = currentTeam?.session_recording_retention_period
    if (!recordingLikelyExpired(observation.created_at, period)) {
        return null
    }
    return (
        <Tooltip
            title={`This session is older than your project's ${recordingRetentionDays(period)}-day recording retention period. The analysis is still available, but the recording can no longer be played.`}
        >
            <LemonTag icon={<IconClock />} type="muted" size="small" data-attr="vision-recording-expired-tag">
                Recording expired
            </LemonTag>
        </Tooltip>
    )
}
