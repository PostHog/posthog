import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { hogFlowsList, workflowDataSuggestionsCurrent } from '../generated/api'

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
        const current = await workflowDataSuggestionsCurrent(projectId).catch(() => null)
        const suggestionDrafts = current?.suggestions.filter((suggestion) => suggestion.draft_workflow_id).length ?? 0
        return suggestionDrafts >= response.count ? 'needs-setup' : 'has-data'
    },
})
