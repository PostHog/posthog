import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'SQL Editor',
    urls: {
        sqlEditor: (query?: string): string => (query ? `/insights/new?q=${query}` : '/insights/new'),
    },
    fileSystemTypes: {
        sql: {
            name: 'SQL editor',
            iconType: 'sql_editor' as FileSystemIconType,
            href: () => urls.sqlEditor(),
            iconColor: ['var(--color-product-data-warehouse-light)'],
            filterKey: 'sql',
        },
    },
    treeItemsProducts: [
        {
            path: 'SQL editor',
            category: 'Analytics',
            type: 'sql',
            iconType: 'sql_editor' as FileSystemIconType,
            iconColor: ['var(--color-product-data-warehouse-light)'] as FileSystemIconColor,
            href: urls.sqlEditor(),
        },
    ],
}
