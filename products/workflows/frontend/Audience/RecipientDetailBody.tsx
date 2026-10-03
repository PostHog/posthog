import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { recipientDetailLogic } from './recipientDetailLogic'
import { RecipientProfile } from './RecipientProfile'

export function RecipientDetailBody(): JSX.Element {
    const { recipientView } = useValues(recipientDetailLogic)
    const { retryLoadRecipient } = useActions(recipientDetailLogic)

    switch (recipientView.state) {
        case 'loading':
            return <LemonSkeleton className="h-64" />
        case 'error':
            return (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: retryLoadRecipient,
                        'data-attr': 'audience-recipient-retry',
                    }}
                >
                    Couldn't load this recipient. Try again in a moment.
                </LemonBanner>
            )
        case 'not-found':
            return (
                <EmptyMessage
                    title="No recipient with this address"
                    description="PostHog no longer has a preference, suppression or person for this address. Go back to the list to see the current recipients."
                />
            )
        case 'found':
            return <RecipientProfile recipient={recipientView.recipient} />
    }
}
