// PROTOTYPE, never merged: PostHog/michaelr-context#419. What Workflows says once messaging has its own home.
import { LemonBanner } from '@posthog/lemon-ui'

import { messagingSectionUrl } from '~/layout/today/messagingNavPrototype/messagingNavPrototypeNav'

export function WorkflowsMovedNotice(): JSX.Element {
    return (
        <LemonBanner type="info" action={{ children: 'Open Email & Messaging', to: messagingSectionUrl('broadcasts') }}>
            Broadcasts, transactional emails, templates and channel setup now live in Email & Messaging. Workflows still
            lists every workflow, including the ones that send messages.
        </LemonBanner>
    )
}
