import { IconToggle } from '@posthog/icons'
import { PRODUCT_VISUAL_ORDER } from 'lib/constants'
import { urls } from 'scenes/urls'

import { ProductManifest } from '../../frontend/src/types'

export const manifest: ProductManifest = {
    name: 'Feature Flags',
    urls: {
        featureFlags: (tab?: string): string => `/feature_flags${tab ? `?tab=${tab}` : ''}`,
        featureFlag: (id: string | number): string => `/feature_flags/${id}`,
        featureFlagDuplicate: (sourceId: number | string | null): string => `/feature_flags/new?sourceId=${sourceId}`,
    },
    fileSystemTypes: {
        feature_flag: {
            icon: <IconToggle />,
            href: (ref: string) => urls.featureFlag(ref),
            iconColor: ['var(--product-feature-flags-light)'],
        },
    },
    treeItemsNew: [
        {
            path: `Feature flag`,
            type: 'feature_flag',
            href: urls.featureFlag('new'),
        },
    ],
    treeItemsProducts: [
        {
            path: `Feature flags`,
            type: 'feature_flag',
            href: urls.featureFlags(),
            visualOrder: PRODUCT_VISUAL_ORDER.featureFlags,
        },
    ],
    fileSystemFilterTypes: {
        feature_flag: { name: 'Feature flags' },
    },
}
