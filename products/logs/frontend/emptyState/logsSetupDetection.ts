import api from 'lib/api'
import type { SetupDetectionProps } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { retryWithBackoff } from 'lib/utils/async'

import { ProductKey } from '~/queries/schema/schema-general'

/**
 * Setup detection for the logs empty state. Binary: the team has ingested at
 * least one log line, or it hasn't - there is no "instrumented but quiet"
 * signal to read, so no waiting-for-data state.
 */
export const logsSetupDetection: SetupDetectionProps = {
    productKey: ProductKey.LOGS,
    detect: async () => {
        const hasLogs = await retryWithBackoff(() => api.logs.hasLogs(), { maxAttempts: 3 })
        return hasLogs ? 'has-data' : 'needs-setup'
    },
    // The first log usually lands moments after the collector restarts, so
    // re-check often enough for the flip to feel immediate.
    pollIntervalMs: 5000,
    cacheHasData: true,
}
