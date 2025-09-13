import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Heatmaps',
    urls: {
        heatmaps: (params?: string): string =>
            `/heatmaps${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    },
    fileSystemTypes: {
        heatmap: {
            name: 'Heatmap',
            iconType: 'heatmap' as FileSystemIconType,
            href: () => urls.heatmaps(),
            iconColor: ['var(--color-product-heatmaps-light)', 'var(--color-product-heatmaps-dark)'],
            filterKey: 'heatmap',
        },
    },
    treeItemsProducts: [
        {
            path: 'Heatmaps',
            category: 'Behavior',
            type: 'heatmap',
            iconType: 'heatmap' as FileSystemIconType,
            iconColor: [
                'var(--color-product-heatmaps-light)',
                'var(--color-product-heatmaps-dark)',
            ] as FileSystemIconColor,
            href: urls.heatmaps(),
            flag: FEATURE_FLAGS.HEATMAPS_UI,
            tags: ['alpha'],
        },
    ],
}
