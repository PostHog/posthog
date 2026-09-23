import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { pulseBriefsList } from '../generated/api'
import { pulseLogic } from '../pulseLogic'

/**
 * Setup detection for the Pulse empty state. Pulse is creation-first: the scene shows
 * generated briefs, so a project with none has nothing to read yet. A brief that is
 * still generating counts, because the scene renders its progress.
 */
export const pulseSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.PULSE,
    path: ['products', 'pulse', 'frontend', 'emptyState', 'pulseSetupLogic'],
    detect: async () => {
        const projectId = String(projectLogic.findMounted()?.values.currentProjectId)
        const response = await pulseBriefsList(projectId, { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
    // The empty state runs the first brief in place, without leaving the scene, so no
    // remount would re-run detection and the gate would keep hiding the new brief.
    recheckActionTypes: () => [pulseLogic.actionTypes.generateBriefSuccess],
})
