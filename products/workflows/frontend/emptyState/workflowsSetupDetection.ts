import type { SetupDetectionProps } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { hogFlowsList } from '../generated/api'

/**
 * Setup detection for the workflows empty state. Workflows are a creation-first
 * product, so "set up" simply means the project has at least one workflow.
 */
export const workflowsSetupDetection: SetupDetectionProps = {
    productKey: ProductKey.WORKFLOWS,
    cacheHasData: true,
    revalidateCachedHasData: true,
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await hogFlowsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
}
