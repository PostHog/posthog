import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { projectLogic } from 'scenes/projectLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { investigationsList } from './generated/api'

export const investigationsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.INVESTIGATIONS,
    path: ['products', 'investigations', 'investigationsSetupLogic'],
    cacheHasData: true,
    revalidateCachedHasData: true,
    detect: async () => {
        const response = await investigationsList(String(projectLogic.values.currentProjectId), { limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
