import * as townCrierPng from '@posthog/brand/hoggies/png/town-crier'
import { IconLetter } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { SubscriptionsPreview } from './SubscriptionsPreview'
import { SubscriptionsPrimaryAction } from './SubscriptionsPrimaryAction'
import { subscriptionsSetupLogic } from './subscriptionsSetupLogic'

const HedgehogTownCrier = pngHoggie(townCrierPng)

export const subscriptionsEmptyState: SceneProductEmptyState = {
    statusLogic: subscriptionsSetupLogic,
    config: {
        productKey: ProductKey.SUBSCRIPTIONS,
        productName: 'Subscriptions',
        icon: <IconLetter />,
        accentColor: 'var(--color-product-subscriptions-light)',
        accentColorDark: 'var(--color-product-subscriptions-dark)',
        hedgehog: HedgehogTownCrier,
        text: {
            'needs-setup': {
                headline: 'Send the numbers to the people who need them',
                lead: 'A subscription re-runs an insight or a dashboard on a schedule and delivers the result to Slack or email. The people who read it never have to open PostHog, and you can ask for a written report from a prompt instead of a chart.',
            },
        },
        PrimaryAction: SubscriptionsPrimaryAction,
        docsUrl: 'https://posthog.com/docs/data/subscriptions',
        previewLabel: 'A subscription, once scheduled',
        Preview: SubscriptionsPreview,
    },
}
