import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'
import { PagePerformanceEmptyState } from 'scenes/web-analytics/PagePerformanceEmptyState'

const CHANNEL_TYPE_DOCS = 'https://posthog.com/docs/data/channel-type'

export const ContentAutopilotTrafficEmptyState = (): JSX.Element => (
    <PagePerformanceEmptyState
        title="No visits from AI assistants in this range"
        action={
            <>
                <LemonButton
                    type="secondary"
                    to={urls.webAnalytics()}
                    data-attr="content-autopilot-ai-traffic-open-web-analytics"
                >
                    Open web analytics
                </LemonButton>
                <LemonButton
                    type="tertiary"
                    to={CHANNEL_TYPE_DOCS}
                    targetBlank
                    data-attr="content-autopilot-ai-traffic-channel-docs"
                >
                    How PostHog spots AI referrals
                </LemonButton>
            </>
        }
    >
        <p className="m-0">
            PostHog counts a session as AI traffic when its referrer or UTM source is an AI assistant. This needs web
            analytics running on your site.
        </p>
        <p className="m-0">Some assistants strip the referrer, so those visits show up as direct traffic.</p>
    </PagePerformanceEmptyState>
)
