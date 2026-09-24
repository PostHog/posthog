import { LemonBanner } from '@posthog/lemon-ui'

import type { AcceptedSuggestion } from '../utils/acceptSuggestion'

export interface SuggestionAcceptedBannerProps {
    accepted: AcceptedSuggestion
    linkLabel: string
    children: React.ReactNode
}

/** What a card shows once its offer is taken: the outcome, and a link to what it created. */
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
