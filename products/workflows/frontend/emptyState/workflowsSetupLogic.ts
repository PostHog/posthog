import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { hogFlowsList, workflowIdeasList } from '../generated/api'

/**
 * Setup detection for the workflows empty state. Workflows are a creation-first
 * product, so "set up" means the project has at least one workflow, or workflows
 * PostHog drafted for it, which the list page shows above the table.
 */
export const workflowsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.WORKFLOWS,
    path: ['products', 'workflows', 'frontend', 'emptyState', 'workflowsSetupLogic'],
    cacheHasData: true,
    revalidateCachedHasData: true,
    // A first visit can render before the flags load, so look again once they arrive.
    recheckActionTypes: () => [featureFlagLogic.actionTypes.setFeatureFlags],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await hogFlowsList(projectId, { limit: 1 })
        if (response.count > 0) {
            return 'has-data'
        }
        if (!featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.WORKFLOWS_IDEAS]) {
            return 'needs-setup'
        }
        const ideas = await workflowIdeasList(projectId).catch(() => null)
        return ideas?.results.length ? 'has-data' : 'needs-setup'
    },
})
