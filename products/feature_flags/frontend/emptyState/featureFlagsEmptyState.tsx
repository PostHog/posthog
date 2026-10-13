import * as trafficControllerPng from '@posthog/brand/hoggies/png/traffic-controller'
import { IconToggle } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

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
                headline: 'Ship code without shipping the feature',
                lead: 'Wrap a change in a feature flag, roll it out to 1% of users, and watch what happens: the session replays, events, and exceptions from the people who got it. Turn it off the moment something looks wrong, no redeploy needed. Flags also power experiments, early access programs, kill switches, and remote config.',
            },
        },
        primaryAction: {
            label: 'Create your first feature flag',
            to: urls.featureFlagTemplates(),
            accessControl: {
                resourceType: AccessControlResourceType.FeatureFlag,
                minAccessLevel: AccessControlLevel.Editor,
            },
            dataAttr: 'new-feature-flag',
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/feature-flags',
        previewLabel: 'Your flags, once created',
        Preview: FeatureFlagPreview,
    },
}
