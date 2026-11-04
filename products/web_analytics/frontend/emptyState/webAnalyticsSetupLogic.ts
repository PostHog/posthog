import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'

/** Web analytics needs nothing beyond posthog-js, so a `$pageview` event definition means it is set up. */
export const webAnalyticsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.WEB_ANALYTICS,
    path: ['products', 'web_analytics', 'frontend', 'emptyState', 'webAnalyticsSetupLogic'],
    cacheHasData: true,
    // Users can delete the `$pageview` definition, so a cached answer is checked again.
    revalidateCachedHasData: true,
    detect: async () => {
        const teamId = teamLogic.findMounted()?.values.currentTeamId
        if (!teamId) {
            return 'unknown'
        }
        const response = await eventDefinitionsList(String(teamId), { names: ['$pageview'], limit: 1 })
        return response.results.some((definition) => definition.name === '$pageview') ? 'has-data' : 'needs-setup'
    },
    pollIntervalMs: 20000,
})
