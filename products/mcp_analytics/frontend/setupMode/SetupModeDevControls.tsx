import { useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

type DevEventKind = 'connect' | 'call' | 'fail'

const DEV_EVENTS: Record<DevEventKind, { label: string; event: string; properties: Record<string, unknown> }> = {
    connect: {
        label: 'Connect server',
        event: '$mcp_initialize',
        properties: { $mcp_client_name: 'claude-code', $mcp_server_name: 'dev-server' },
    },
    call: {
        label: 'Send tool call',
        event: '$mcp_tool_call',
        properties: {
            $mcp_client_name: 'claude-code',
            $mcp_server_name: 'dev-server',
            $mcp_tool_name: 'search_docs',
            $mcp_intent: 'Find the rate limit for the billing API so I can add retries',
            $mcp_is_error: false,
            $mcp_duration_ms: 142,
            $mcp_response: 'Billing API: 100 requests per minute per key.',
        },
    },
    fail: {
        label: 'Send failed call',
        event: '$mcp_tool_call',
        properties: {
            $mcp_client_name: 'cursor',
            $mcp_server_name: 'dev-server',
            $mcp_tool_name: 'create_issue',
            $mcp_intent: 'Open a ticket for the 429 errors the user reported',
            $mcp_is_error: true,
            $mcp_duration_ms: 88,
            $mcp_error_message: 'ValidationError: missing required field "team_id"',
        },
    },
}

/**
 * Dev-only buttons that send real MCP events to the current project, so setup mode advances through
 * the same ingestion and polling a live server would trigger. Renders nothing in production builds.
 */
export function SetupModeDevControls(): JSX.Element | null {
    if (process.env.NODE_ENV !== 'development') {
        return null
    }
    return <SetupModeDevControlsContent />
}

function SetupModeDevControlsContent(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const [sending, setSending] = useState<DevEventKind | null>(null)

    if (!currentTeam?.api_token) {
        return null
    }
    const token = currentTeam.api_token

    const send = async (kind: DevEventKind): Promise<void> => {
        const { event, properties } = DEV_EVENTS[kind]
        setSending(kind)
        try {
            const response = await fetch('/e/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: token, event, distinct_id: 'setup-mode-dev', properties }),
            })
            if (!response.ok) {
                throw new Error(`capture answered ${response.status}`)
            }
            lemonToast.success(`Sent ${event}. Setup mode moves on at its next poll.`)
        } catch (error) {
            lemonToast.error(`Couldn't send ${event}: ${String(error)}`)
        } finally {
            setSending(null)
        }
    }

    return (
        // Bottom center, clear of toasts (bottom right) and the wizard sync debug panel (bottom left).
        <div className="fixed bottom-2 left-1/2 z-[9999] -translate-x-1/2 flex items-center gap-1 rounded border bg-surface-primary p-1 text-xs shadow-md">
            <span className="px-1 font-semibold">Dev: advance setup</span>
            {(Object.keys(DEV_EVENTS) as DevEventKind[]).map((kind) => (
                <LemonButton
                    key={kind}
                    size="xsmall"
                    type="secondary"
                    loading={sending === kind}
                    disabledReason={sending && sending !== kind ? 'Sending another event' : undefined}
                    onClick={() => void send(kind)}
                >
                    {DEV_EVENTS[kind].label}
                </LemonButton>
            ))}
        </div>
    )
}
