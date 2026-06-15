import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { visionScannersList, visionScannersObserveCreate } from '../generated/api'
import type { ReplayScannerApi } from '../generated/api.schemas'
import type { bulkScanLogicType } from './bulkScanLogicType'

export const bulkScanLogic = kea<bulkScanLogicType>([
    path(['products', 'replay_vision', 'frontend', 'logics', 'bulkScanLogic']),

    connect(() => ({
        actions: [teamLogic, ['loadCurrentTeamSuccess']],
    })),

    actions({
        scanRecordings: (scannerId: string, sessionIds: string[]) => ({ scannerId, sessionIds }),
        scanRecordingsSuccess: true,
        scanRecordingsFailure: true,
    }),

    loaders({
        scanners: [
            [] as ReplayScannerApi[],
            {
                loadScanners: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return []
                    }
                    try {
                        const response = await visionScannersList(String(teamId))
                        return response.results ?? []
                    } catch {
                        return []
                    }
                },
            },
        ],
    }),

    reducers({
        scanning: [
            false,
            {
                scanRecordings: () => true,
                scanRecordingsSuccess: () => false,
                scanRecordingsFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        scanRecordings: async ({ scannerId, sessionIds }) => {
            const teamId = teamLogic.values.currentTeamId
            if (sessionIds.length === 0) {
                lemonToast.error('Select at least one recording to scan')
                actions.scanRecordingsFailure()
                return
            }
            if (!teamId) {
                actions.scanRecordingsFailure()
                return
            }
            // The backend keys the workflow on (scanner, session) and silently no-ops duplicates,
            // so re-running the same pair is safe and needs no client-side dedup.
            const results = await Promise.allSettled(
                sessionIds.map((session_id) => visionScannersObserveCreate(String(teamId), scannerId, { session_id }))
            )
            const failed = results.filter((r) => r.status === 'rejected').length
            const started = results.length - failed
            const scannerName = values.scanners.find((s) => s.id === scannerId)?.name ?? 'scanner'

            if (started > 0) {
                lemonToast.success(
                    `Started scanning ${started} recording${started === 1 ? '' : 's'} with “${scannerName}”`,
                    {
                        button: {
                            label: 'Go to scanner page',
                            action: () => router.actions.push(urls.replayVision(scannerId)),
                            dataAttr: 'vision-bulk-scan-go-to-scanner',
                        },
                    }
                )
            }
            if (failed > 0) {
                lemonToast.error(`Failed to start scanning ${failed} recording${failed === 1 ? '' : 's'}`)
            }
            actions.scanRecordingsSuccess()
        },
        // The logic is global/propless, so reload scanners when the active team changes
        // to avoid POSTing the previous team's scanner IDs to the new team's endpoint.
        loadCurrentTeamSuccess: () => {
            actions.loadScanners()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadScanners()
    }),
])
