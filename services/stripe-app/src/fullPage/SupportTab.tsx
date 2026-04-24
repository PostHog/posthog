import { Box } from '@stripe/ui-extension-sdk/ui'

import type { PostHogClient } from '../posthog/client'
import PromoBanner, { PromoBannerPrimaryLink, PromoBannerText, PromoBannerTitle } from './components/PromoBanner'

interface Props {
    client: PostHogClient | null
    projectId: string | null
}

const SupportTab = ({ client, projectId }: Props): JSX.Element => {
    const posthogBase = client ? `${client.baseUrl}/project/${projectId}` : null

    return (
        <Box css={{ width: 'fill', padding: 'large' }}>
            <PromoBanner hero>
                <PromoBannerTitle>Support is coming to PostHog</PromoBannerTitle>
                <PromoBannerText>
                    Soon you'll be able to correlate your PostHog users with Stripe customers and respond to support
                    tickets directly from PostHog — with full context from session replays, feature flags, and product
                    analytics already attached.
                </PromoBannerText>
                {posthogBase && (
                    <PromoBannerPrimaryLink href={`${posthogBase}/support`}>
                        Learn more about PostHog Support
                    </PromoBannerPrimaryLink>
                )}
            </PromoBanner>
        </Box>
    )
}

export default SupportTab
