import Stripe from 'stripe'

import type { AppConstants } from '../constants'
import { logger } from '../logger'

export type Region = 'us' | 'eu'

// Keep in sync with the secret names defined in posthog/models/integration.py
export const SECRET_NAMES = {
    region: 'posthog_region',
    accessToken: 'posthog_access_token',
    refreshToken: 'posthog_refresh_token',
    projectId: 'posthog_project_id',
    oauthClientId: 'posthog_oauth_client_id',
} as const

// Every value we load out of the Stripe Secret Store lives on this single object.
export interface StoredCredentials {
    region: Region
    accessToken: string
    refreshToken: string
    projectId: string
    clientId: string
}

// Narrower shape used by rotation flows (dev token entry + refreshAccessToken) — only
// the three rotating fields are written, so project_id / oauth_client_id aren't touched.
export type RotatingTokens = Pick<StoredCredentials, 'region' | 'accessToken' | 'refreshToken'>

export async function loadCredentials(stripe: Stripe): Promise<StoredCredentials | null> {
    logger.debug('Loading credentials from Stripe Secret Store...')
    const scope = accountScope()

    try {
        const [region, accessToken, refreshToken, projectId, oauthClientId] = await Promise.all([
            findSecret<Region>(stripe, SECRET_NAMES.region, scope),
            findSecret(stripe, SECRET_NAMES.accessToken, scope),
            findSecret(stripe, SECRET_NAMES.refreshToken, scope),
            findSecret(stripe, SECRET_NAMES.projectId, scope),
            findSecret(stripe, SECRET_NAMES.oauthClientId, scope),
        ])

        logger.debug('Credentials state:', {
            region: region ?? 'missing',
            projectId: projectId ?? 'missing',
            oauthClientId: oauthClientId ?? 'missing',
            accessToken: accessToken ? 'present' : 'missing',
            refreshToken: refreshToken ? 'present' : 'missing',
        })

        if (!region || !accessToken || !refreshToken || !projectId || !oauthClientId) {
            logger.info('Credentials incomplete, returning disconnected state')
            return null
        }

        logger.info('Credentials loaded successfully, region:', region)
        return {
            region,
            accessToken,
            refreshToken,
            projectId,
            clientId: oauthClientId,
        }
    } catch (e) {
        logger.error('Failed to load credentials:', e)
        return null
    }
}

export async function saveCredentials(stripe: Stripe, tokens: RotatingTokens): Promise<void> {
    logger.info('Saving credentials to Stripe Secret Store...')
    const scope = accountScope()

    try {
        await Promise.all([
            stripe.apps.secrets.create({ name: SECRET_NAMES.region, payload: tokens.region, scope }),
            stripe.apps.secrets.create({ name: SECRET_NAMES.accessToken, payload: tokens.accessToken, scope }),
            stripe.apps.secrets.create({ name: SECRET_NAMES.refreshToken, payload: tokens.refreshToken, scope }),
        ])
        logger.info('Credentials saved successfully')
    } catch (e) {
        logger.error('Failed to save credentials:', e)
        throw e
    }
}

// Writes every field production fills in — used by the dev-mode sign-in form so a paste-in
// session mirrors what the real OAuth flow stores. Rotation uses `saveCredentials` to avoid
// touching `project_id` / `oauth_client_id`.
export async function saveAllCredentials(stripe: Stripe, credentials: StoredCredentials): Promise<void> {
    logger.info('Saving full credentials (tokens + project_id + client_id) to Stripe Secret Store...')
    const scope = accountScope()

    try {
        await Promise.all([
            stripe.apps.secrets.create({ name: SECRET_NAMES.region, payload: credentials.region, scope }),
            stripe.apps.secrets.create({ name: SECRET_NAMES.accessToken, payload: credentials.accessToken, scope }),
            stripe.apps.secrets.create({ name: SECRET_NAMES.refreshToken, payload: credentials.refreshToken, scope }),
            stripe.apps.secrets.create({ name: SECRET_NAMES.projectId, payload: credentials.projectId, scope }),
            stripe.apps.secrets.create({ name: SECRET_NAMES.oauthClientId, payload: credentials.clientId, scope }),
        ])
        logger.info('Full credentials saved successfully')
    } catch (e) {
        logger.error('Failed to save full credentials:', e)
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
            stripe.apps.secrets.deleteWhere({ name: SECRET_NAMES.projectId, scope }),
            stripe.apps.secrets.deleteWhere({ name: SECRET_NAMES.oauthClientId, scope }),
        ])
        logger.info('Credentials cleared successfully')
    } catch (e) {
        logger.error('Failed to clear credentials:', e)
        throw e
    }
}

export function getBaseUrlForRegion(region: Region, constants: AppConstants): string {
    return region === 'eu' ? constants.POSTHOG_EU_BASE_URL : constants.POSTHOG_US_BASE_URL
}

function accountScope(): Stripe.Apps.SecretCreateParams['scope'] {
    return { type: 'account' }
}

async function findSecret<T = string>(
    stripe: Stripe,
    name: string,
    scope: Stripe.Apps.SecretCreateParams['scope']
): Promise<T | null> {
    try {
        const secret = await stripe.apps.secrets.find({ name, scope, expand: ['payload'] })
        return (secret.payload as T) ?? null
    } catch (e) {
        logger.debug(`Failed to load secret ${name}:`, e)
        return null
    }
}
