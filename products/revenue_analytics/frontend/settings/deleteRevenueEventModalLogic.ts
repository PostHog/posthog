import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DataWarehouseManagedViewsetSavedQuery } from '~/types'

import type { deleteRevenueEventModalLogicType } from './deleteRevenueEventModalLogicType'

export const deleteRevenueEventModalLogic = kea<deleteRevenueEventModalLogicType>([
    path(['products', 'revenue_analytics', 'settings', 'deleteRevenueEventModalLogic']),

    actions({
        setEventName: (eventName: string | null) => ({ eventName }),
    }),

    reducers({
        eventName: [
            null as string | null,
            {
                setEventName: (_, { eventName }) => eventName,
            },
        ],
    }),

    loaders(() => ({
        views: [
            [] as DataWarehouseManagedViewsetSavedQuery[],
            {
                setEventName: async ({ eventName }, breakpoint) => {
                    if (!eventName) {
                        return []
                    }

                    try {
                        const response = await api.dataWarehouseManagedViewsets.getViews('revenue_analytics')
                        await breakpoint(100)

                        const eventPrefix = eventName.replace(/\s+/g, '_').toLowerCase()
                        const views = response.views.filter((view) => view.name.includes(eventPrefix))
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
