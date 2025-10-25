import { urls } from 'scenes/urls'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Feature Flags',
    urls: {
        featureFlags: (tab?: string): string => `/feature_flags${tab ? `?tab=${tab}` : ''}`,
        featureFlag: (id: string | number): string => `/feature_flags/${id}`,
        featureFlagDuplicate: (sourceId: number | string | null): string => `/feature_flags/new?sourceId=${sourceId}`,
    },
    fileSystemTypes: {
        feature_flag: {
            name: 'Feature flag',
            iconType: 'feature_flag',
            href: (ref: string) => urls.featureFlag(ref),
            iconColor: ['var(--color-product-feature-flags-light)'],
            filterKey: 'feature_flag',
        },
    },
    treeItemsNew: [
        {
            path: `Feature flag`,
            type: 'feature_flag',
            href: urls.featureFlag('new'),
            iconType: 'feature_flag',
            iconColor: ['var(--color-product-feature-flags-light)'] as FileSystemIconColor,
        },
    ],
    treeItemsProducts: [
        {
            path: `Feature flags`,
            category: 'Features',
            type: 'feature_flag',
            href: urls.featureFlags(),
            sceneKey: 'FeatureFlags',
        },
    ],
}
