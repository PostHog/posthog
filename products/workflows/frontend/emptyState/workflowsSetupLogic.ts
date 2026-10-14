import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { hogFlowsList } from '../generated/api'

/**
 * Setup detection for the workflows empty state. Workflows are a creation-first
 * product, so "set up" simply means the project has at least one workflow.
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
        if (response.count === 0) {
            return 'needs-setup'
        }
        if (!featureFlagLogic.findMounted()?.values.featureFlags[FEATURE_FLAGS.WORKFLOWS_DATA_SUGGESTIONS]) {
            return 'has-data'
        }
        // Drafts made from suggestions keep the empty state, where their cards say "In draft" and link to them.
        const suggestionDrafts = await hogFlowsList(projectId, { limit: 1, origin_product: 'ideas', status: 'draft' })
        return suggestionDrafts.count === response.count ? 'needs-setup' : 'has-data'
    },
})
