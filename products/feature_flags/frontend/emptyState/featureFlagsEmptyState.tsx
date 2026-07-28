import * as trafficControllerPng from '@posthog/brand/hoggies/png/traffic-controller'
import { IconToggle } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

import { FeatureFlagPreview } from './FeatureFlagPreview'
import { featureFlagsSetupLogic } from './featureFlagsSetupLogic'

const HedgehogTrafficController = pngHoggie(trafficControllerPng)

export const featureFlagsEmptyState: SceneProductEmptyState = {
    statusLogic: featureFlagsSetupLogic,
    config: {
        productKey: ProductKey.FEATURE_FLAGS,
        productName: 'Feature flags',
        icon: <IconToggle />,
        accentColor: 'var(--color-product-feature-flags-light)',
        hedgehog: HedgehogTrafficController,
        text: {
            'needs-setup': {
                headline: 'Release features safely, roll back instantly',
                lead: 'Turn features on for specific users, roll them out gradually, and switch them off the moment something breaks. No redeploy needed.',
            },
        },
        primaryAction: { label: 'Create your first feature flag', to: urls.featureFlag('new') },
        docsUrl: 'https://posthog.com/docs/feature-flags',
        previewLabel: 'Your flags, once created',
        Preview: FeatureFlagPreview,
    },
}
