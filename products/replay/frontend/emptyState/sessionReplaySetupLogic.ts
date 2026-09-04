import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import { ProductKey } from '~/queries/schema/schema-general'

/**
 * Setup detection for the session replay empty state. Recordings exist → has-data;
 * recording is on but the project never ingested an event → no-events, because
 * waiting cannot help until the SDK reaches PostHog; recording on without
 * recordings yet → waiting-for-data; recording off → needs-setup. No has-data
 * cache: recordings expire with retention, so a positive answer is not permanent.
 */
export const sessionReplaySetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.SESSION_REPLAY,
    path: ['products', 'replay', 'frontend', 'emptyState', 'sessionReplaySetupLogic'],
    detect: async () => {
        const response = await api.recordings.list({ kind: NodeKind.RecordingsQuery, limit: 1 })
        if (response.results.length > 0) {
            return 'has-data'
        }
        const mountedTeamLogic = teamLogic.findMounted()
        const currentTeam = mountedTeamLogic?.values.currentTeam
        if (!currentTeam?.session_recording_opt_in) {
            return 'needs-setup'
        }
        // Only an explicit `false` counts: the flag is absent from some team payloads, and
        // reading that as "no events" would tell a working project its SDK is broken.
        if (currentTeam.ingested_event !== false) {
            return 'waiting-for-data'
        }
        // The server sets `ingested_event`, and nothing else refreshes the team while this
        // screen stays open, so the value the page booted with can be stale. Re-read the team
        // before we send anyone to check an installation that now works. Only a project that
        // has sent nothing pays for the extra request, and the first event ends it.
        await mountedTeamLogic?.asyncActions.loadCurrentTeam()
        return mountedTeamLogic?.values.currentTeam?.ingested_event === false ? 'no-events' : 'waiting-for-data'
    },
    pollIntervalMs: 20000,
    // Enabling recording (from this empty state or settings) must flip the
    // screen to "waiting" right away, not on the next poll tick.
    recheckActionTypes: () => [teamLogic.actionTypes.updateCurrentTeamSuccess],
})
