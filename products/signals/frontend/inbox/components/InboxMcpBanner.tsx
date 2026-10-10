import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

export function InboxMcpBanner(): JSX.Element | null {
    const { user } = useValues(userLogic)

    return (
        <LemonBanner
            type="info"
            dismissKey={`inbox-mcp-banner-${user?.uuid ?? 'anonymous'}`}
            className="!bg-fill-info-secondary"
            action={{
                children: 'Install PostHog MCP',
                type: 'primary',
                status: 'alt',
                to: 'https://posthog.com/docs/model-context-protocol#get-started-in-30-seconds',
                targetBlank: true,
                'data-attr': 'inbox-mcp-banner-install',
            }}
        >
            Use the self-driving inbox with your agents through PostHog MCP.
        </LemonBanner>
    )
}
