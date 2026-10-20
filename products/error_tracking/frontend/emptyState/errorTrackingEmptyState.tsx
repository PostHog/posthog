import * as errorPng from '@posthog/brand/hoggies/png/error'
import { IconWarning } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { ErrorTrackingPreview } from './ErrorTrackingPreview'
import { errorTrackingSetupLogic } from './errorTrackingSetupLogic'

const HedgehogError = pngHoggie(errorPng)

export const errorTrackingEmptyState: SceneProductEmptyState = {
    statusLogic: errorTrackingSetupLogic,
    config: {
        productKey: ProductKey.ERROR_TRACKING,
        productName: 'Error tracking',
        icon: <IconWarning />,
        accentColor: 'var(--color-product-error-tracking-light)',
        accentColorDark: 'var(--color-product-error-tracking-dark)',
        hedgehog: HedgehogError,
        text: {
            'needs-setup': {
                headline: 'Catch the errors your users actually hit',
                lead: 'PostHog captures exceptions from your app and groups them into issues, with stack traces, affected users, and alerts. Triage, assign, and resolve them next to the rest of your product data.',
                hint: 'Check your SDK integration and set up exception capture and source map upload if needed:',
            },
            'waiting-for-data': {
                headline: 'Waiting for the first exception',
                lead: "Exception autocapture is enabled for this project, but that alone doesn't confirm your app sends exceptions. Check that your app is configured to capture exceptions.",
            },
        },
        wizard: { slug: 'error-tracking', pinProjectId: true },
        docsUrl: 'https://posthog.com/docs/error-tracking',
        manualSetupUrl: 'https://posthog.com/docs/error-tracking/installation',
        previewLabel: 'Issues, once exceptions arrive',
        Preview: ErrorTrackingPreview,
    },
}
