import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { notebooksList } from '../generated/api'

/**
 * Setup detection for the notebooks empty state. Notebooks are a creation-first
 * product, so "set up" means the project has at least one notebook. Templates the
 * table lists alongside them are local, so they never count as a notebook.
 */
export const notebooksSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.NOTEBOOKS,
    path: ['products', 'notebooks', 'frontend', 'emptyState', 'notebooksSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await notebooksList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
