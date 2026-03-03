import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context'
import { createHttpClient, STRIPE_API_KEY } from '@stripe/ui-extension-sdk/http_client'
import { SignInView, Spinner } from '@stripe/ui-extension-sdk/ui'
import { useEffect, useState } from 'react'
import Stripe from 'stripe'

import { BRAND_COLOR, BrandIcon, getConstants } from '../constants'
import { logger } from '../logger'
import { loadCredentials } from '../posthog/auth'

const stripe = new Stripe(STRIPE_API_KEY, {
    httpClient: createHttpClient(),
})

const Onboarding = ({ environment }: ExtensionContextValue): JSX.Element => {
    const constants = getConstants(environment)
    const [connected, setConnected] = useState<boolean | null>(null)

    useEffect(() => {
        logger.debug('Onboarding: checking connection status...')
        loadCredentials(stripe)
            .then((creds) => {
                logger.info('Onboarding: connected =', creds !== null)
                setConnected(creds !== null)
            })
            .catch((error) => {
                logger.error('Onboarding: error checking credentials:', error)
                setConnected(false)
            })
    }, [])

    if (connected === null) {
        return (
            <SignInView brandColor={BRAND_COLOR} brandIcon={BrandIcon} description="Loading...">
                <Spinner />
            </SignInView>
        )
    }

    if (connected) {
        return (
            <SignInView
                brandColor={BRAND_COLOR}
                brandIcon={BrandIcon}
                description="You're connected to PostHog. Navigate to a customer to see their analytics data."
            />
        )
    }

    return (
        <SignInView
            brandColor={BRAND_COLOR}
            brandIcon={BrandIcon}
            description="Connect this Stripe account from your PostHog dashboard to see product analytics data alongside your customers."
            primaryAction={{
                label: 'Open PostHog',
                href: constants.POSTHOG_DASHBOARD_URL,
                target: '_blank',
            }}
        />
    )
}

export default Onboarding
