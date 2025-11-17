import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DataWarehouseManagedViewsetSavedQuery, ExternalDataSource } from '~/types'

import type { disableRevenueSourceModalLogicType } from './disableRevenueSourceModalLogicType'

export const disableRevenueSourceModalLogic = kea<disableRevenueSourceModalLogicType>([
    path(['products', 'revenue_analytics', 'settings', 'disableRevenueSourceModalLogic']),

    actions({
        setSource: (source: ExternalDataSource | null) => ({ source }),
    }),

    reducers({
        source: [
            null as ExternalDataSource | null,
            {
                setSource: (_, { source }) => source,
            },
        ],
    }),

    loaders(() => ({
        views: [
            [] as DataWarehouseManagedViewsetSavedQuery[],
            {
                setSource: async ({ source }, breakpoint) => {
                    if (!source) {
                        return []
                    }

                    try {
                        const response = await api.dataWarehouseManagedViewsets.getViews('revenue_analytics')
                        await breakpoint(100)

                        // Filter views by source prefix (e.g., "stripe.my_prefix")
                        const sourcePrefix = source.prefix
                            ? `${source.source_type.toLowerCase()}.${source.prefix}`
                            : source.source_type.toLowerCase()

                        const views = response.views.filter((view) => view.name.startsWith(sourcePrefix))
                        return views
                    } catch (error) {
                        console.error('Failed to fetch views:', error)
                        return []
                    }
                },
            },
        ],
    })),
])
