import { createHttpClient, STRIPE_API_KEY } from '@stripe/ui-extension-sdk/http_client'
import { Banner, Box, Button, Inline, Link, Select, Spinner, TextField } from '@stripe/ui-extension-sdk/ui'
import { useCallback, useEffect, useState } from 'react'
import Stripe from 'stripe'

import type { AppConstants } from '../constants'
import { logger } from '../logger'
import { clearCredentials, loadCredentials, saveCredentials, type Region } from '../posthog/auth'

const stripe = new Stripe(STRIPE_API_KEY, {
    httpClient: createHttpClient(),
})

type ConnectionState = { status: 'loading' } | { status: 'disconnected' } | { status: 'connected'; region: Region }

interface PostHogConnectProps {
    constants: AppConstants
    mode: 'live' | 'test'
}

const PostHogConnect = ({ constants, mode }: PostHogConnectProps): JSX.Element => {
    const [connectionState, setConnectionState] = useState<ConnectionState>({
        status: 'loading',
    })

    const checkCredentials = useCallback((): void => {
        logger.debug('PostHogConnect: checking credentials...')
        loadCredentials(stripe)
            .then((creds) => {
                if (creds) {
                    logger.info('PostHogConnect: connected, region:', creds.region)
                    setConnectionState({ status: 'connected', region: creds.region })
                } else {
                    logger.info('PostHogConnect: not connected')
                    setConnectionState({ status: 'disconnected' })
                }
            })
            .catch((error) => {
                logger.info('PostHogConnect: error checking credentials:', error)
                setConnectionState({ status: 'disconnected' })
            })
    }, [])

    useEffect(() => {
        checkCredentials()
    }, [checkCredentials])

    const handleDisconnect = useCallback(async (): Promise<void> => {
        await clearCredentials(stripe)
        setConnectionState({ status: 'disconnected' })
    }, [])

    if (connectionState.status === 'loading') {
        return (
            <Box css={{ stack: 'x', alignX: 'center', padding: 'large' }}>
                <Spinner />
            </Box>
        )
    }

    if (connectionState.status === 'connected') {
        return (
            <Box css={{ stack: 'y', rowGap: 'medium' }}>
                <Banner
                    type="default"
                    title="Connected to PostHog"
                    description={`Region: ${connectionState.region.toUpperCase()}`}
                />
                <Banner
                    type="default"
                    description={
                        <Inline>
                            This app connects your Stripe data to PostHog's Data warehouse for analysis.{' '}
                            <Link href="https://posthog.com/docs/cdp/sources/stripe" target="_blank">
                                Learn more
                            </Link>
                        </Inline>
                    }
                />
                <Button
                    type="primary"
                    href={`${constants.POSTHOG_DASHBOARD_URL}/settings/project-integrations`}
                    target="_blank"
                >
                    Manage in PostHog
                </Button>
                {mode === 'test' && (
                    <Button type="destructive" onPress={handleDisconnect}>
                        Clear credentials
                    </Button>
                )}
            </Box>
        )
    }

    return (
        <Box css={{ stack: 'y', rowGap: 'medium' }}>
            <Banner
                type="caution"
                title="Not connected to PostHog"
                description="Connect this Stripe account from your PostHog dashboard to see product analytics data here."
            />
            <Button type="primary" href={constants.POSTHOG_NEW_SOURCE_URL} target="_blank">
                Connect in PostHog
            </Button>
            <Button onPress={checkCredentials}>Refresh connection status</Button>
            {mode === 'test' && <DevTokenEntry onSaved={checkCredentials} />}
        </Box>
    )
}

const DevTokenEntry = ({ onSaved }: { onSaved: () => void }): JSX.Element => {
    const [region, setRegion] = useState<Region>('us')
    const [accessToken, setAccessToken] = useState('')
    const [refreshToken, setRefreshToken] = useState('')
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const handleSave = useCallback(async (): Promise<void> => {
        if (!accessToken || !refreshToken) {
            setError('Both tokens are required')
            return
        }

        setSaving(true)
        setError(null)
        try {
            await saveCredentials(stripe, { region, accessToken, refreshToken })
            setAccessToken('')
            setRefreshToken('')
            onSaved()
        } catch (e) {
            logger.error('DevTokenEntry: failed to save credentials:', e)
            setError('Failed to save credentials')
        } finally {
            setSaving(false)
        }
    }, [region, accessToken, refreshToken, onSaved])

    return (
        <Box css={{ stack: 'y', rowGap: 'small', marginTop: 'medium' }}>
            <Banner
                type="default"
                title="Dev mode"
                description="Paste tokens from manage.py generate_stripe_app_tokens"
            />
            <Select label="Region" value={region} onChange={(e): void => setRegion(e.target.value as Region)}>
                <option value="us">US</option>
                <option value="eu">EU</option>
            </Select>
            <TextField
                label="Access token"
                value={accessToken}
                onChange={(e): void => setAccessToken(e.target.value)}
            />
            <TextField
                label="Refresh token"
                value={refreshToken}
                onChange={(e): void => setRefreshToken(e.target.value)}
            />
            {error && <Banner type="critical" title={error} />}
            <Button type="primary" onPress={handleSave} disabled={saving}>
                {saving ? 'Saving...' : 'Save tokens'}
            </Button>
        </Box>
    )
}

export default PostHogConnect
