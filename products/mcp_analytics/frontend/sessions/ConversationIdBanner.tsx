import { useActions, useValues } from 'kea'

import * as organizedPng from '@posthog/brand/hoggies/png/organized'

import { pngHoggie } from 'lib/brand/hoggies'

import { FixWithAgentButton } from '../components/FixWithAgentButton'
import { ActivityCard } from '../earlyData/ActivityCard'
import { INSTRUMENTATION_FIXES } from '../instrumentationFixes'
import { mcpSessionsLogic } from './mcpSessionsLogic'

const OrganizedHog = pngHoggie(organizedPng)

export function ConversationIdBanner(): JSX.Element | null {
    const { showConversationIdBanner } = useValues(mcpSessionsLogic)
    const { dismissConversationIdBanner } = useActions(mcpSessionsLogic)

    if (!showConversationIdBanner) {
        return null
    }
    const fix = INSTRUMENTATION_FIXES.sessions
    return (
        <ActivityCard
            illustration={OrganizedHog}
            title="Group tool calls into sessions"
            description="Almost every session holds a single tool call, which is typical for stateless servers. Conversation IDs stitch the calls of one conversation together."
            primaryControl={<FixWithAgentButton fix={fix} dataAttr="mcp-sessions-conversation-id-fix" />}
            secondaryAction={{
                label: 'Docs',
                to: fix.docsUrl,
                targetBlank: true,
                dataAttr: 'mcp-sessions-conversation-id-docs',
            }}
            onDismiss={dismissConversationIdBanner}
        />
    )
}
