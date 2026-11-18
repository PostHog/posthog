import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { engineeringAnalyticsEnable, engineeringAnalyticsSources } from '../generated/api'

/**
 * A project is set up once it has a GitHub warehouse source connected, synced or not, because the
 * scene explains an unsynced source itself.
 *
 * Opening the product with a source connected is the opt-in that lets background work run for
 * the project. Enabling needs editor access, so a viewer's failure is ignored and the next editor
 * enables it.
 */
export const engineeringAnalyticsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.ENGINEERING_ANALYTICS,
    path: ['products', 'engineering_analytics', 'frontend', 'emptyState', 'engineeringAnalyticsSetupLogic'],
    cacheHasData: true,
    revalidateCachedHasData: true,
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const sources = await engineeringAnalyticsSources(projectId)
        if (sources.length === 0) {
            return 'needs-setup'
        }
        void engineeringAnalyticsEnable(projectId).catch(() => undefined)
        return 'has-data'
    },
})
