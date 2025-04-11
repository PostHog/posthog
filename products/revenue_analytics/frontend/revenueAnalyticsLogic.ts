import { kea, path, selectors } from 'kea'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { revenueAnalyticsLogicType } from './revenueAnalyticsLogicType'

export const revenueAnalyticsLogic = kea<revenueAnalyticsLogicType>([
    path(['products', 'revenueAnalytics', 'frontend', 'revenueAnalyticsLogic']),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: 'RevenueAnalytics',
                    name: 'Revenue analytics',
                    path: urls.revenueAnalytics(),
                },
            ],
        ],
    }),
])
