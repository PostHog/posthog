import { IconRocket } from '@posthog/icons'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Early access features',
    scenes: {
        EarlyAccessFeatures: {
            name: 'Early access features',
            import: () => import('./frontend/EarlyAccessFeatures'),
            projectBased: true,
            defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
            activityScope: 'EarlyAccessFeature',
        },
        EarlyAccessFeature: {
            name: 'Early access feature',
            import: () => import('./frontend/EarlyAccessFeature'),
            projectBased: true,
            defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
            activityScope: 'EarlyAccessFeature',
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
            icon: <IconRocket />,
            href: (ref: string) => urls.earlyAccessFeature(ref),
            iconColor: ['var(--product-early-access-features-primary)', 'var(--product-early-access-features-primary)'],
        },
    },
    treeItemsNew: [
        {
            path: `Early access feature`,
            type: 'early_access_feature',
            href: urls.earlyAccessFeature('new'),
        },
    ],
    treeItemsProducts: [],
    fileSystemFilterTypes: {
        early_access_feature: { name: 'Early access features' },
    },
}
