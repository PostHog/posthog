import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonBanner } from '@posthog/lemon-ui'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'

export function InboxAgentSetupComplete(): JSX.Element | null {
    const { completed } = useValues(inboxSetupLogic)
    const { searchParams } = useValues(router)

    return completed && searchParams.agent_setup === 'complete' ? (
        <LemonBanner type="success">Self-driving is set up. You can now continue in your agent.</LemonBanner>
    ) : null
}
