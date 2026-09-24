import * as errorPng from '@posthog/brand/hoggies/png/error'
import { IconWarning } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import type { SceneProductEmptyState } from 'lib/components/ProductEmptyState/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

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
                hint: 'Already using posthog-js? One click and errors start flowing:',
            },
            'waiting-for-data': {
                headline: "You're set up. Waiting for the first exception",
                lead: 'Exception capture is on. When your app throws, the error shows up here on its own, grouped into an issue with its stack trace.',
            },
        },
        // Autocapture is already on in `waiting-for-data`, so the opt-in only belongs on the setup screen.
        primaryAction: {
            'needs-setup': {
                label: 'Enable exception autocapture',
                onClick: () => {
                    const mounted = teamLogic.findMounted()
                    mounted?.actions.addProductIntent({
                        product_type: ProductKey.ERROR_TRACKING,
                        intent_context: ProductIntentContext.ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED,
                    })
                    mounted?.actions.updateCurrentTeam({ autocapture_exceptions_opt_in: true })
                },
                accessControl: {
                    resourceType: AccessControlResourceType.ErrorTracking,
                    minAccessLevel: AccessControlLevel.Editor,
                },
            },
        },
        docsUrl: 'https://posthog.com/docs/error-tracking',
        manualSetupUrl: 'https://posthog.com/docs/error-tracking/installation',
        previewLabel: 'Issues, once exceptions arrive',
        Preview: ErrorTrackingPreview,
        // The `error-tracking` wizard subcommand is still rolling out. While its flag is on the terminal
        // card is the only call to action, so the one-click opt-in and its lead-in leave the setup screen.
        // The wizard is keyed to setup: once autocapture is on the screen only waits for an exception.
        featureFlagOverrides: {
            [FEATURE_FLAGS.ERROR_TRACKING_NEW_WIZARD]: {
                text: {
                    'needs-setup': {
                        hint: 'Run Wizard in your project. The setup agent installs the SDK if needed, then adds exception capture and source map upload:',
                    },
                },
                wizard: { 'needs-setup': { slug: 'error-tracking', pinProjectId: true } },
                primaryAction: undefined,
            },
        },
    },
}
