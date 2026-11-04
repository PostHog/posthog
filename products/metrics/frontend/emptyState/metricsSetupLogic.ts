import posthog from 'posthog-js'

import { isFeatureFlagGatedError } from 'lib/api-error'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { retryWithBackoff } from 'lib/utils/async'
import { addProductIntent } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { metricsHasMetricsRetrieve } from '../generated/api'
import { canViewMetrics } from '../metricsAccess'

// Session-scoped intent state: only an observed no-metrics -> has-metrics
// transition counts as first ingestion. A team whose first check already
// returns true (or was cached true) just has pre-existing metrics.
let sawNoMetrics = false
let firstIngestIntentFired = false
// Derived series also report `has-data`, but only ingested metrics count as first ingestion.
let hasIngestedMetrics = false

/**
 * Setup detection for the metrics empty state. Binary: the team has ingested at
 * least one metric sample, or it hasn't. Without viewer access the check cannot
 * run, so the status is `unknown` and the gate fails open to the scene, whose
 * own access controls take over.
 */
export const metricsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.METRICS,
    path: ['products', 'metrics', 'frontend', 'emptyState', 'metricsSetupLogic'],
    detect: async () => {
        if (!canViewMetrics()) {
            return 'unknown'
        }
        const teamId = teamLogic.findMounted()?.values.currentTeamId
        if (!teamId) {
            return 'unknown'
        }
        try {
            const response = await retryWithBackoff(() => metricsHasMetricsRetrieve(String(teamId)), {
                maxAttempts: 3,
            })
            if (response.hasDerivedSources) {
                // Exposure for the derived series experiment: both variants reach this point only when the
                // team has spans or logs to derive series from. posthog-js reports each flag value once per session.
                posthog.getFeatureFlag(FEATURE_FLAGS.METRICS_DERIVED_SERIES)
            }
            if (response.hasMetrics) {
                hasIngestedMetrics = true
                return 'has-data'
            }
            // The test variant charts derived series, so it skips the setup screen.
            return response.hasDerivedMetrics ? 'has-data' : 'needs-setup'
        } catch (error) {
            // The alpha enrollment has not reached the server yet: it arrives as an ingested
            // person property, so a user who just turned the feature preview on is still denied
            // for a few seconds. That is not a detection failure worth an error toast - report
            // `unknown` and let the next poll answer.
            if (isFeatureFlagGatedError(error)) {
                return 'unknown'
            }
            throw error
        }
    },
    onDetected: (status) => {
        if (status === 'needs-setup') {
            sawNoMetrics = true
        }
        if (status === 'has-data' && hasIngestedMetrics && sawNoMetrics && !firstIngestIntentFired) {
            firstIngestIntentFired = true
            void addProductIntent({
                product_type: ProductKey.METRICS,
                intent_context: ProductIntentContext.METRICS_FIRST_INGESTED,
            })
        }
    },
    // The first sample usually lands moments after the agent starts, so re-check
    // often enough for the flip to feel immediate.
    pollIntervalMs: 5000,
    cacheHasData: true,
})
