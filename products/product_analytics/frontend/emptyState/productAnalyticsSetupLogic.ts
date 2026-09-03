import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { insightsList } from '../generated/api'

/**
 * Setup detection for the product analytics empty state. The gated scene is the
 * saved insights list, so "set up" means the project has at least one saved
 * insight - not that events are arriving, which the scene does not depend on.
 */
export const productAnalyticsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.PRODUCT_ANALYTICS,
    path: ['products', 'product_analytics', 'frontend', 'emptyState', 'productAnalyticsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await insightsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
