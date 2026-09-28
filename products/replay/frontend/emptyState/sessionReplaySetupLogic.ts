import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { retentionPeriodDateFrom } from 'scenes/session-recordings/utils'
import { teamLogic } from 'scenes/teamLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { ProductKey } from '~/queries/schema/schema-general'

/**
 * Setup detection for the session replay empty state. Three-state: recordings
 * exist → has-data; recording opt-in without recordings yet → waiting-for-data;
 * neither → needs-setup. Recordings expire with retention, so a cached has-data
 * answer is revalidated in the background instead of trusted forever.
 */
export const sessionReplaySetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.SESSION_REPLAY,
    path: ['products', 'replay', 'frontend', 'emptyState', 'sessionReplaySetupLogic'],
    cacheHasData: true,
    revalidateCachedHasData: true,
    detect: async () => {
        const currentTeam = teamLogic.findMounted()?.values.currentTeam
        // The recordings list defaults to the last 3 days, which reads a project whose newest
        // recording is older than that as "nothing captured". Scan the whole retention period.
        const response = await api.recordings.list({
            kind: NodeKind.RecordingsQuery,
            limit: 1,
            date_from: retentionPeriodDateFrom(currentTeam?.session_recording_retention_period),
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
