import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { ProductManifest } from '~/types'

export const manifest: ProductManifest = {
    name: 'Revenue Analytics',
    treeItemsMetadata: [
        {
            path: 'Revenue definitions',
            category: 'Schema',
            iconType: 'revenue_analytics_metadata' as FileSystemIconType,
            iconColor: ['var(--color-product-revenue-analytics-light)', 'var(--color-product-revenue-analytics-dark)'],
            href: urls.revenueSettings(),
            sceneKey: 'DataManagement',
        },
    ],
}
