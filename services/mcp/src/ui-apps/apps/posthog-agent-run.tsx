import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import {
    type AgentOperation,
    agentViewCancelArguments,
    agentViewReplyArguments,
    agentViewStatusArguments,
} from '../../tools/posthogAgent/operations'
import { AgentOperationView, isTerminal } from '../components/AgentOperationView'
import { AppWrapper } from '../components/AppWrapper'
import { useToolPolling } from '../hooks/useToolPolling'
import { parseToolResultContent } from '../hooks/useToolResult'

/** Calls an operation tool, then replaces the polled data with the operation it returns. */
function useOperationAction(
    app: App | null,
    setData: (operation: AgentOperation) => void,
    fallbackError: string
): {
    pending: string | null
    error: string | null
    run: (key: string, name: string, args: Record<string, unknown>) => Promise<void>
} {
    const [pending, setPending] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    const run = useCallback(
        async (key: string, name: string, args: Record<string, unknown>): Promise<void> => {
            if (!app || pending) {
                return
            }
            setPending(key)
            setError(null)
            try {
                const result = await app.callServerTool({ name, arguments: args })
                const next = result.isError
                    ? null
                    : parseToolResultContent<AgentOperation>(result.structuredContent, result._meta)
                if (next) {
                    setData(next)
                } else {
                    const text = result.content?.find((c) => c.type === 'text')
                    setError(text && 'text' in text ? text.text : fallbackError)
                }
            } catch (e) {
                setError(e instanceof Error ? e.message : String(e))
            } finally {
                setPending(null)
            }
        },
        [app, pending, setData, fallbackError]
    )

    return { pending, error, run }
}

function PostHogAgentRunContent({ data, app }: { data: AgentOperation; app: App | null }): JSX.Element {
    const {
        data: operation,
        error,
        setData,
    } = useToolPolling<AgentOperation>({
        app,
        initialData: data,
        toolName: 'posthog-agent-status',
        getArguments: agentViewStatusArguments,
        isDone: isTerminal,
        getIntervalSeconds: (op) => op.retry_after_seconds,
    })
    const cancel = useOperationAction(app, setData, 'Could not cancel the operation.')
    const reply = useOperationAction(app, setData, 'Could not send the reply.')

    const current = operation ?? data

    return (
        <AgentOperationView
            operation={current}
            onOpenLink={(url) => (app ? void app.openLink({ url }) : window.open(url, '_blank', 'noopener,noreferrer'))}
            canControl={!!app}
            pollError={error}
            onCancel={() => void cancel.run('cancel', 'posthog-agent-cancel', agentViewCancelArguments(current))}
            cancelling={cancel.pending !== null}
            cancelError={cancel.error}
            onReply={(message) =>
                void reply.run(
                    message,
                    'posthog-agent-reply',
                    agentViewReplyArguments(current, message, crypto.randomUUID())
                )
            }
            pendingReply={reply.pending}
            replyError={reply.error}
        />
    )
}

function PostHogAgentRunApp(): JSX.Element {
    return (
        <AppWrapper<AgentOperation> appName="PostHog Agent">
            {({ data, app }) => <PostHogAgentRunContent data={data!} app={app} />}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<PostHogAgentRunApp />)
}
