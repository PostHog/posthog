import api from 'lib/api'
import { createSetupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'

import { ProductKey } from '~/queries/schema/schema-general'

/**
 * Setup detection for the heatmaps empty state. Heatmaps are creation-first: the
 * scene lists saved heatmaps, so a project with none has nothing to show yet, even
 * when heatmap data is already being collected. Re-checks on every mount (the gate
 * mounts it), which covers returning from the "new heatmap" page.
 */
export const heatmapsSetupLogic = createSetupDetectionLogic({
    productKey: ProductKey.HEATMAPS,
    path: ['products', 'web_analytics', 'frontend', 'heatmaps', 'emptyState', 'heatmapsSetupLogic'],
    detect: async () => {
        const response = await api.savedHeatmaps.list({ limit: 1 })
        return response.count > 0 ? 'has-data' : 'needs-setup'
    },
})
