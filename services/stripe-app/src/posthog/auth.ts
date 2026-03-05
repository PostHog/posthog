import Stripe from 'stripe'

import type { AppConstants } from '../constants'
import { logger } from '../logger'

export type Region = 'us' | 'eu'

// Keep in sync with the secret names defined in posthog/models/integration.py
export const SECRET_NAMES = {
    region: 'posthog_region',
    accessToken: 'posthog_access_token',
    refreshToken: 'posthog_refresh_token',
} as const

export interface StoredCredentials {
    region: Region
    accessToken: string
    refreshToken: string
}

export function getBaseUrlForRegion(region: Region, constants: AppConstants): string {
    return region === 'eu' ? constants.POSTHOG_EU_BASE_URL : constants.POSTHOG_US_BASE_URL
}

function accountScope(): Stripe.Apps.SecretCreateParams['scope'] {
    return { type: 'account' }
}

export async function loadCredentials(stripe: Stripe): Promise<StoredCredentials | null> {
    logger.debug('Loading credentials from Stripe Secret Store...')
    const scope = accountScope()
    try {
        const [regionSecret, accessSecret, refreshSecret] = await Promise.all([
            stripe.apps.secrets.find({ name: SECRET_NAMES.region, scope, expand: ['payload'] }),
            stripe.apps.secrets.find({ name: SECRET_NAMES.accessToken, scope, expand: ['payload'] }),
            stripe.apps.secrets.find({ name: SECRET_NAMES.refreshToken, scope, expand: ['payload'] }),
        ])

        const hasRegion = !!regionSecret.payload
        const hasAccessToken = !!accessSecret.payload
        const hasRefreshToken = !!refreshSecret.payload

        logger.debug('Credentials state:', {
            region: hasRegion ? regionSecret.payload : 'missing',
            accessToken: hasAccessToken ? 'present' : 'missing',
            refreshToken: hasRefreshToken ? 'present' : 'missing',
        })

        if (!hasRegion || !hasAccessToken || !hasRefreshToken) {
            logger.info('Credentials incomplete, returning disconnected state')
            return null
        }

        logger.info('Credentials loaded successfully, region:', regionSecret.payload)
        return {
            region: regionSecret.payload as Region,
            accessToken: accessSecret.payload!,
            refreshToken: refreshSecret.payload!,
        }
    } catch (e) {
        logger.error('Failed to load credentials:', e)
        return null
    }
}

export async function saveCredentials(stripe: Stripe, credentials: StoredCredentials): Promise<void> {
    logger.info('Saving credentials to Stripe Secret Store...')
    const scope = accountScope()
    try {
        await Promise.all([
            stripe.apps.secrets.create({ name: SECRET_NAMES.region, payload: credentials.region, scope }),
            stripe.apps.secrets.create({ name: SECRET_NAMES.accessToken, payload: credentials.accessToken, scope }),
            stripe.apps.secrets.create({
                name: SECRET_NAMES.refreshToken,
                payload: credentials.refreshToken,
                scope,
            }),
        ])
        logger.info('Credentials saved successfully')
    } catch (e) {
        logger.error('Failed to save credentials:', e)
        throw e
    }
}

export async function clearCredentials(stripe: Stripe): Promise<void> {
    logger.info('Clearing all stored credentials...')
    const scope = accountScope()
    try {
        await Promise.all([
            stripe.apps.secrets.deleteWhere({ name: SECRET_NAMES.region, scope }),
            stripe.apps.secrets.deleteWhere({ name: SECRET_NAMES.accessToken, scope }),
            stripe.apps.secrets.deleteWhere({ name: SECRET_NAMES.refreshToken, scope }),
        ])
        logger.info('Credentials cleared successfully')
    } catch (e) {
        logger.error('Failed to clear credentials:', e)
        throw e
    }
}
