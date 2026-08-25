import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Feature Flags',
    scenes: {
        FeatureFlagTemplates: {
            import: () => import('./frontend/FeatureFlagTemplatesScene'),
            projectBased: true,
            name: 'Feature flag templates',
        },
        FeatureFlagsStaffTools: {
            import: () => import('./frontend/staff/FeatureFlagsStaffToolsScene'),
            instanceLevel: true,
            name: 'Flags staff tools',
        },
    },
    routes: {
        '/feature_flags/templates': ['FeatureFlagTemplates', 'featureFlagTemplates'],
        '/feature_flags/staff': ['FeatureFlagsStaffTools', 'featureFlagsStaffTools'],
    },
    urls: {
        featureFlag: (id: string | number): string => `/feature_flags/${id}`,
        featureFlags: (tab?: string): string => `/feature_flags${tab ? `?tab=${tab}` : ''}`,
        featureFlagTemplates: (): string => '/feature_flags/templates',
        featureFlagsStaffTools: (teamId?: number): string =>
            `/feature_flags/staff${teamId ? `?team_id=${teamId}` : ''}`,
        featureFlagNew: ({
            type,
            sourceId,
            template,
            intent,
        }: {
            type?: 'boolean' | 'multivariate' | 'remote_config'
            sourceId?: number | string | null
            template?: 'simple' | 'targeted' | 'multivariate' | 'targeted-multivariate'
            intent?: 'local-eval' | 'first-page-load'
        }): string => {
            const params = new URLSearchParams()
            if (type) {
                params.set('type', type)
            }
            if (sourceId) {
                params.set('sourceId', sourceId.toString())
            }
            if (template) {
                params.set('template', template)
            }
            if (intent) {
                params.set('intent', intent)
            }
            return `/feature_flags/new?${params.toString()}`
        },
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
            intents: [ProductKey.FEATURE_FLAGS, ProductKey.EXPERIMENTS, ProductKey.EARLY_ACCESS_FEATURES],
            category: ProductItemCategory.FEATURES,
            type: 'feature_flag',
            href: urls.featureFlags(),
            sceneKey: 'FeatureFlags',
            sceneKeys: ['FeatureFlags', 'FeatureFlag'],
        },
    ],
}
