import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { ProductKey } from '~/queries/schema/schema-general'
import type { SessionRecordingRetentionPeriod } from '~/types'

// The recordings list defaults to the last 3 days server-side, which reads a project whose newest
// recording is older than that as "nothing captured" and hides the scene behind the waiting
// screen. Probe the project's retention period instead: no recording can outlive it, so it is the
// widest window worth scanning. `legacy` (not a duration) and an unset period fall back to 90
// days, as the recordings API does.
function probeDateFrom(period: SessionRecordingRetentionPeriod | null | undefined): string {
    return `-${period && period !== 'legacy' ? period : '90d'}`
}

/**
 * Setup detection for the session replay empty state. Three-state: recordings
 * exist → has-data; recording opt-in without recordings yet → waiting-for-data;
 * neither → needs-setup. No has-data cache: recordings expire with retention,
 * so a positive answer is not permanent.
 */
export const sessionReplaySetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.SESSION_REPLAY,
    path: ['products', 'replay', 'frontend', 'emptyState', 'sessionReplaySetupLogic'],
    detect: async () => {
        const currentTeam = teamLogic.findMounted()?.values.currentTeam
        const response = await api.recordings.list({
            kind: NodeKind.RecordingsQuery,
            limit: 1,
            date_from: probeDateFrom(currentTeam?.session_recording_retention_period),
        })
        if (response.results.length > 0) {
            return 'has-data'
        }
        return currentTeam?.session_recording_opt_in ? 'waiting-for-data' : 'needs-setup'
    },
    pollIntervalMs: 20000,
    // Enabling recording (from this empty state or settings) must flip the
    // screen to "waiting" right away, not on the next poll tick.
    recheckActionTypes: () => [teamLogic.actionTypes.updateCurrentTeamSuccess],
})
