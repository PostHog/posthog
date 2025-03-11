import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Early Access Features',
    scenes: {
        EarlyAccessFeatures: {
            name: 'Early Access Features',
            import: () => import('./frontend/EarlyAccessFeatures'),
            projectBased: true,
            defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
            activityScope: 'EarlyAccessFeature',
        },
        EarlyAccessFeature: {
            name: 'Early Access Features',
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
}
