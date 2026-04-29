import type { ExtensionContextValue } from '@stripe/ui-extension-sdk/context'
import { createHttpClient, STRIPE_API_KEY } from '@stripe/ui-extension-sdk/http_client'
import { Box, FullPageTab, FullPageTabs, FullPageView, SignInView, Spinner } from '@stripe/ui-extension-sdk/ui'
import { useCallback, useEffect, useState } from 'react'
import Stripe from 'stripe'

import { DevTokenEntry } from '../components/PostHogConnect'
import { appendSandboxParam, BRAND_COLOR, BrandIcon, getConstants } from '../constants'
import EventsTab from '../fullPage/EventsTab'
import ExperimentsTab from '../fullPage/ExperimentsTab'
import FeatureFlagsTab from '../fullPage/FeatureFlagsTab'
import OverviewTab from '../fullPage/OverviewTab'
import { logger } from '../logger'
import { getBaseUrlForRegion, loadCredentials } from '../posthog/auth'
import { PostHogClient } from '../posthog/client'

const stripe = new Stripe(STRIPE_API_KEY, { httpClient: createHttpClient() })

type ConnectionState =
    | { status: 'loading' }
    | { status: 'disconnected' }
    | { status: 'connected'; client: PostHogClient; projectId: string | null }

const DISCONNECTED_DESCRIPTION =
    'PostHog gives you product analytics, session replays, experiments, and feature flags for your Stripe customers. ' +
    'To get started, connect this Stripe account from your PostHog dashboard.'

const FullPage = ({ environment, userContext }: ExtensionContextValue): JSX.Element => {
    const [state, setState] = useState<ConnectionState>({ status: 'loading' })

    // The runtime passes a fresh `environment` prop on every render, so anything derived
    // from it needs to be captured once on mount — otherwise hook deps change each render
    // and we end up in a render → fetch → setState loop.
    const [constants] = useState(() => getConstants(environment))
    const [mode] = useState<'live' | 'test'>(() => environment?.mode ?? 'live')
    const [isSandbox] = useState<boolean>(() => userContext?.account?.isSandbox ?? false)

    const loadConnection = useCallback(async (): Promise<void> => {
        try {
            const credentials = await loadCredentials(stripe)
            if (!credentials) {
                setState({ status: 'disconnected' })
                return
            }

            const baseUrl = getBaseUrlForRegion(credentials.region, constants)
            const client = new PostHogClient({
                baseUrl,
                stripe,
                accessToken: credentials.accessToken,
                refreshToken: credentials.refreshToken,
                clientId: credentials.clientId,
            })

            setState({ status: 'connected', client, projectId: credentials.projectId })
        } catch (e) {
            logger.error('FullPage failed to load credentials:', e)
            setState({ status: 'disconnected' })
        }
    }, [constants])

    useEffect(() => {
        void loadConnection()
    }, [loadConnection])

    if (state.status === 'loading') {
        return (
            <FullPageView>
                <Box css={{ stack: 'x', alignX: 'center', padding: 'xlarge' }}>
                    <Spinner />
                </Box>
            </FullPageView>
        )
    }

    if (state.status === 'disconnected') {
        return (
            <FullPageView>
                <SignInView
                    brandColor={BRAND_COLOR}
                    brandIcon={BrandIcon}
                    description={DISCONNECTED_DESCRIPTION}
                    descriptionActionLabel="Learn more"
                    primaryAction={{
                        label: 'Connect in PostHog',
                        href: appendSandboxParam(constants.POSTHOG_NEW_SOURCE_URL, isSandbox),
                        target: '_blank',
                    }}
                    secondaryAction={{
                        label: "Don't have an account? Sign up",
                        href: constants.POSTHOG_DASHBOARD_URL,
                        target: '_blank',
                    }}
                    footerContent={mode === 'test' ? <DevTokenEntry onSaved={loadConnection} /> : undefined}
                />
            </FullPageView>
        )
    }

    const { client, projectId } = state

    return (
        <FullPageView>
            <FullPageTabs>
                <FullPageTab
                    id="overview"
                    label="Overview"
                    content={<OverviewTab client={client} projectId={projectId} />}
                />
                <FullPageTab id="events" label="Events" content={<EventsTab client={client} projectId={projectId} />} />
                <FullPageTab
                    id="experiments"
                    label="Experiments"
                    content={<ExperimentsTab client={client} projectId={projectId} />}
                />
                <FullPageTab
                    id="feature-flags"
                    label="Feature flags"
                    content={<FeatureFlagsTab client={client} projectId={projectId} />}
                />
                {/*
                 * Support tab is hidden from the UI for now but kept around so we can re-enable it easily.
                 * <FullPageTab
                 *     id="support"
                 *     label="Support"
                 *     content={<SupportTab client={client} projectId={projectId} />}
                 * />
                 */}
            </FullPageTabs>
        </FullPageView>
    )
}

export default FullPage
