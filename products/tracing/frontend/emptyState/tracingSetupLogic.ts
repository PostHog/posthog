import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { retryWithBackoff } from 'lib/utils/async'

import { ProductKey } from '~/queries/schema/schema-general'

/**
 * Setup detection for the tracing empty state. Binary: the team has ingested at
 * least one span, or it hasn't - there is no "instrumented but quiet" signal to
 * read, so no waiting-for-data state.
 */
export const tracingSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.TRACING,
    path: ['products', 'tracing', 'frontend', 'emptyState', 'tracingSetupLogic'],
    detect: async () => {
        const hasSpans = await retryWithBackoff(() => api.tracing.hasSpans(), { maxAttempts: 3 })
        return hasSpans ? 'has-data' : 'needs-setup'
    },
    // The first span usually lands moments after the collector restarts, so
    // re-check often enough for the flip to feel immediate.
    pollIntervalMs: 5000,
    cacheHasData: true,
})
