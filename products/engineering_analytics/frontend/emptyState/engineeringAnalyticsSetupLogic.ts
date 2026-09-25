import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { engineeringAnalyticsSources } from '../generated/api'

/**
 * Setup detection for the engineering analytics empty state. The product reads pull
 * requests and workflow runs from a GitHub warehouse source, so a project is set up once
 * it has one connected, synced or not: the scene explains an unsynced source itself.
 */
export const engineeringAnalyticsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.ENGINEERING_ANALYTICS,
    path: ['products', 'engineering_analytics', 'frontend', 'emptyState', 'engineeringAnalyticsSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const sources = await engineeringAnalyticsSources(projectId)
        return sources.length > 0 ? 'has-data' : 'needs-setup'
    },
})
