import { IconToggle } from '@posthog/icons'
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
        },
    },
    treeItemsNew: [
        {
            path: `Feature flag`,
            type: 'feature_flag',
            href: () => urls.featureFlag('new'),
        },
    ],
}
