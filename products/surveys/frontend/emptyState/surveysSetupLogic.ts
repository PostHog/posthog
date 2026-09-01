import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { surveysList } from '../generated/api'

/**
 * Setup detection for the surveys empty state. Surveys are a creation-first
 * product, so "set up" simply means the project has at least one survey - no
 * event or traffic signal involved.
 */
export const surveysSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.SURVEYS,
    path: ['products', 'surveys', 'frontend', 'emptyState', 'surveysSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        // The list excludes archived surveys unless asked for them, and no value of
        // `archived` returns both, so a project that archived all of its surveys
        // would count zero and lose the scene it unarchives them from.
        const [live, archived] = await Promise.all([
            surveysList(projectId, { limit: 1 }),
            surveysList(projectId, { limit: 1, archived: true }),
        ])
        return live.count + archived.count > 0 ? 'has-data' : 'needs-setup'
    },
})
