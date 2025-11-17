import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Early access features',
    scenes: {
        EarlyAccessFeatures: {
            name: 'Early access features',
            import: () => import('./frontend/EarlyAccessFeatures'),
            projectBased: true,
            defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
            description: 'Allow your users to individually enable or disable features that are in public beta.',
            iconType: 'early_access_feature',
        },
        EarlyAccessFeature: {
            name: 'Early access feature',
            import: () => import('./frontend/EarlyAccessFeature'),
            projectBased: true,
            defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
        },
    },
    routes: {
        '/early_access_features': ['EarlyAccessFeatures', 'earlyAccessFeatures'],
        '/early_access_features/:id': ['EarlyAccessFeature', 'earlyAccessFeature'],
    },
    redirects: {},
    urls: {
        earlyAccessFeatures: (): string => '/early_access_features',
        earlyAccessFeature:
            /** @param id A UUID or 'new'. ':id' for routing. */
            (id: string): string => `/early_access_features/${id}`,
    },
    fileSystemTypes: {
        early_access_feature: {
            name: 'Early access feature',
            iconType: 'early_access_feature' as FileSystemIconType,
            href: (ref: string) => urls.earlyAccessFeature(ref),
            iconColor: [
                'var(--color-product-early-access-features-light)',
                'var(--color-product-early-access-features-dark)',
            ],
            filterKey: 'early_access_feature',
        },
    },
    treeItemsNew: [
        {
            path: `Early access feature`,
            type: 'early_access_feature',
            href: urls.earlyAccessFeature('new'),
            iconType: 'early_access_feature' as FileSystemIconType,
            iconColor: [
                'var(--color-product-early-access-features-light)',
                'var(--color-product-early-access-features-dark)',
            ] as FileSystemIconColor,
        },
    ],
    treeItemsProducts: [
        {
            path: 'Early access features',
            category: 'Features',
            type: 'early_access_feature',
            href: urls.earlyAccessFeatures(),
            iconType: 'early_access_feature' as FileSystemIconType,
            iconColor: [
                'var(--color-product-early-access-features-light)',
                'var(--color-product-early-access-features-dark)',
            ] as FileSystemIconColor,
            sceneKey: 'EarlyAccessFeatures',
        },
    ],
}
