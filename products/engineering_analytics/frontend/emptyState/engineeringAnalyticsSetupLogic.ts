import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { engineeringAnalyticsEnable, engineeringAnalyticsSources } from '../generated/api'

/**
 * Setup detection for the engineering analytics empty state. The product reads pull
 * requests and workflow runs from a GitHub warehouse source, so a project is set up once
 * it has one connected, synced or not: the scene explains an unsynced source itself.
 *
 * Opening the product with a source connected is the opt-in: it enables the project, which
 * is what lets the background work (view sync, test census, CI failure logs) run for it.
 * The call is idempotent and does nothing for an enabled project. It needs editor access, so
 * a viewer's failure is ignored: the scene still renders, and the next editor enables it.
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
