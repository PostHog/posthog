import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
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
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await hogFlowsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
