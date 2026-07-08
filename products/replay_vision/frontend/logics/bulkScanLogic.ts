import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { router } from 'kea-router'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { visionScannersObserveCreate } from '../generated/api'
import type { bulkScanLogicType } from './bulkScanLogicType'
import { refreshVisionQuota } from './visionQuotaLogic'
import { visionScannersListLogic } from './visionScannersListLogic'

// Caps simultaneous workflow-start requests; the batches run sequentially.
const BULK_SCAN_CONCURRENCY = 10

export const bulkScanLogic = kea<bulkScanLogicType>([
    path(['products', 'replay_vision', 'frontend', 'logics', 'bulkScanLogic']),

    connect(() => ({
        values: [visionScannersListLogic, ['scanners', 'scannersLoading']],
    })),

    actions({
        scanRecordings: (scannerId: string, sessionIds: string[]) => ({ scannerId, sessionIds }),
        scanRecordingsSuccess: true,
        scanRecordingsFailure: true,
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
            // The backend keys the workflow on (scanner, session) and no-ops duplicates, so no client-side dedup.
            let started = 0
            let failed = 0
            let firstError: ApiError | null = null
            let quotaError: ApiError | null = null
            // Batched so selecting hundreds of recordings doesn't fire hundreds of simultaneous workflow starts.
            for (let i = 0; i < sessionIds.length && !quotaError; i += BULK_SCAN_CONCURRENCY) {
                const batch = sessionIds.slice(i, i + BULK_SCAN_CONCURRENCY)
                const results = await Promise.allSettled(
                    batch.map((session_id) => visionScannersObserveCreate(String(teamId), scannerId, { session_id }))
                )
                for (const result of results) {
                    if (result.status === 'fulfilled') {
                        started += 1
                        continue
                    }
                    failed += 1
                    if (result.reason instanceof ApiError) {
                        firstError = firstError ?? result.reason
                        if (result.reason.status === 402) {
                            quotaError = result.reason // Quota is org-wide — the rest of the batch would 402 too.
                        }
                    }
                }
            }
            const skipped = sessionIds.length - started - failed
            const scannerName = values.scanners.find((s) => s.id === scannerId)?.name ?? 'scanner'

            if (started > 0) {
                refreshVisionQuota()
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
            if (quotaError) {
                const detail = quotaError.detail ?? 'Monthly Replay Vision quota reached.'
                lemonToast.error(skipped > 0 ? `${detail} Skipped ${skipped} remaining recordings.` : detail)
            } else if (failed > 0) {
                lemonToast.error(
                    `Failed to start scanning ${failed} recording${failed === 1 ? '' : 's'}${
                        firstError?.detail ? `: ${firstError.detail}` : ''
                    }`
                )
            }
            actions.scanRecordingsSuccess()
        },
    })),
])
