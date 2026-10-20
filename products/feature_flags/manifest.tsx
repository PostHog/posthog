import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductItemCategory, ProductKey } from '~/queries/schema/schema-general'

import { AnyPropertyFilter, FileSystemIconColor, ProductManifest } from '../../frontend/src/types'

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
        // nosemgrep: frontend-route-hyphen -- shipped app URL, existing links point here
        '/feature_flags/templates': ['FeatureFlagTemplates', 'featureFlagTemplates'],
        // nosemgrep: frontend-route-hyphen -- shipped app URL, existing links point here
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
            format,
            properties,
        }: {
            type?: 'boolean' | 'multivariate' | 'remote_config'
            sourceId?: number | string | null
            template?: 'simple' | 'targeted' | 'multivariate' | 'targeted-multivariate'
            intent?: 'local-eval' | 'first-page-load'
            format?: 'rules_v2'
            /** Release condition properties for a single condition set rolled out to 100%. */
            properties?: AnyPropertyFilter[]
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
            if (format) {
                params.set('format', format)
            }
            if (properties?.length) {
                params.set('properties', JSON.stringify(properties))
            }
            return `/feature_flags/new?${params.toString()}`
        },
    },
    fileSystemTypes: {
        feature_flag: {
            name: 'Feature flag',
            iconType: 'feature_flag',
            href: (ref: string) => urls.featureFlag(ref),
            listHref: () => urls.featureFlags(),
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
            category: ProductItemCategory.PRODUCT_ENGINEERING,
            type: 'feature_flag',
            href: urls.featureFlags(),
            searchKeywords: ['toggles', 'rollouts', 'remote config', 'kill switch'],
            searchTabs: [
                {
                    name: 'Request usage',
                    href: urls.featureFlags('usage'),
                    flag: FEATURE_FLAGS.FEATURE_FLAG_REQUEST_USAGE,
                },
                { name: 'Projects', href: urls.featureFlags('projects') },
                {
                    name: 'Notifications',
                    href: urls.featureFlags('notifications'),
                    flag: FEATURE_FLAGS.FEATURE_FLAG_NOTIFICATIONS,
                },
            ],
            sceneKey: 'FeatureFlags',
            sceneKeys: ['FeatureFlags', 'FeatureFlag'],
        },
    ],
}
