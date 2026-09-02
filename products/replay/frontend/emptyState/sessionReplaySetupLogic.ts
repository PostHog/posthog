import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { ProductKey } from '~/queries/schema/schema-general'

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
        const response = await api.recordings.list({ kind: NodeKind.RecordingsQuery, limit: 1 })
        if (response.results.length > 0) {
            return 'has-data'
        }
        return teamLogic.findMounted()?.values.currentTeam?.session_recording_opt_in
            ? 'waiting-for-data'
            : 'needs-setup'
    },
    pollIntervalMs: 20000,
    // Enabling recording (from this empty state or settings) must flip the
    // screen to "waiting" right away, not on the next poll tick.
    recheckActionTypes: () => [teamLogic.actionTypes.updateCurrentTeamSuccess],
})
