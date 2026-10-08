import { LemonBanner } from '@posthog/lemon-ui'

import type { AcceptedSuggestion } from '../utils/acceptSuggestion'

export interface SuggestionAcceptedBannerProps {
    accepted: AcceptedSuggestion
    linkLabel: string
    children: React.ReactNode
}

export function SuggestionAcceptedBanner({
    accepted,
    linkLabel,
    children,
}: SuggestionAcceptedBannerProps): JSX.Element {
    return (
        <LemonBanner
            type={accepted.slackConnected ? 'success' : 'warning'}
            action={{ to: accepted.url, children: linkLabel }}
        >
            {children}
        </LemonBanner>
    )
}
