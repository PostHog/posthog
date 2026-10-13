import * as rocketPng from '@posthog/brand/hoggies/png/rocket'
import { IconRocket } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EarlyAccessFeaturePreview } from './EarlyAccessFeaturePreview'
import { earlyAccessFeaturesSetupLogic } from './earlyAccessFeaturesSetupLogic'

const HedgehogRocket = pngHoggie(rocketPng)

export const earlyAccessFeaturesEmptyState: SceneProductEmptyState = {
    statusLogic: earlyAccessFeaturesSetupLogic,
    config: {
        productKey: ProductKey.EARLY_ACCESS_FEATURES,
        productName: 'Early access features',
        icon: <IconRocket />,
        accentColor: 'var(--color-product-early-access-features-light)',
        accentColorDark: 'var(--color-product-early-access-features-dark)',
        hedgehog: HedgehogRocket,
        text: {
            'needs-setup': {
                headline: 'Run beta programs without building your own',
                lead: 'Let users opt in and out of features at any stage, from early concepts to general availability. Run beta programs, collect waitlists for upcoming features, and give users control of their product experience, all without custom infrastructure. Each feature links to a flag, and a user opting in overrides its release conditions.',
            },
        },
        primaryAction: {
            label: 'Create your first early access feature',
            to: urls.earlyAccessFeature('new'),
            accessControl: {
                resourceType: AccessControlResourceType.EarlyAccessFeature,
                minAccessLevel: AccessControlLevel.Editor,
            },
            dataAttr: 'create-feature',
        },
        skippable: false,
        docsUrl: 'https://posthog.com/docs/feature-flags/early-access-feature-management',
        previewLabel: 'Your betas, once published',
        Preview: EarlyAccessFeaturePreview,
    },
}
