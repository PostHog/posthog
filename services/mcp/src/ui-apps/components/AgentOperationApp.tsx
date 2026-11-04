import type { App } from '@modelcontextprotocol/ext-apps'
import { type ReactElement, useCallback, useState } from 'react'

import {
    type AgentOperation,
    agentViewCancelArguments,
    agentViewReplyArguments,
    agentViewStatusArguments,
} from '../../tools/posthogAgent/operations'
import { useToolPolling } from '../hooks/useToolPolling'
import { parseToolResultContent } from '../hooks/useToolResult'
import { AgentOperationView, type AgentOperationVariant, isTerminal } from './AgentOperationView'
import { AppWrapper } from './AppWrapper'

/** Calls an operation tool, then replaces the shown operation with the one it returns. */
function useOperationAction(
    app: App | null,
    setData: (operation: AgentOperation) => void,
    fallbackError: string
): {
    pending: string | null
    error: string | null
    run: (key: string, name: string, args: Record<string, unknown>) => Promise<boolean>
} {
    const [pending, setPending] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    const run = useCallback(
        async (key: string, name: string, args: Record<string, unknown>): Promise<boolean> => {
            if (!app || pending) {
                return false
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
                    return true
                }
                const text = result.content?.find((c) => c.type === 'text')
                setError(text && 'text' in text ? text.text : fallbackError)
            } catch (e) {
                setError(e instanceof Error ? e.message : String(e))
            } finally {
                setPending(null)
            }
            return false
        },
        [app, pending, setData, fallbackError]
    )

    return { pending, error, run }
}

function AgentOperationContent({
    data,
    app,
    variant,
}: {
    data: AgentOperation
    app: App | null
    variant: AgentOperationVariant
}): ReactElement {
    const {
        data: operation,
        error,
        setData,
    } = useToolPolling<AgentOperation>({
        app,
        initialData: data,
        toolName: 'posthog-agent-status',
        getArguments: agentViewStatusArguments,
        // An update card is a snapshot. It only keeps reading while it waits for the user, so that an
        // answer given elsewhere clears it.
        isDone: variant === 'run' ? isTerminal : (op) => op.state !== 'needs_input',
        getIntervalSeconds: (op) => op.retry_after_seconds,
    })
    const cancel = useOperationAction(app, setData, 'Could not cancel the run. Try again.')
    const reply = useOperationAction(app, setData, 'Could not send your reply. Try again.')
    const [answered, setAnswered] = useState<string | null>(null)

    const current = operation ?? data

    return (
        <AgentOperationView
            operation={current}
            variant={variant}
            onOpenLink={(url) => (app ? void app.openLink({ url }) : window.open(url, '_blank', 'noopener,noreferrer'))}
            canControl={!!app}
            pollError={error}
            onCancel={() => void cancel.run('cancel', 'posthog-agent-cancel', agentViewCancelArguments(current))}
            cancelling={cancel.pending !== null}
            cancelError={cancel.error}
            onReply={(message) =>
                void reply
                    .run(message, 'posthog-agent-reply', agentViewReplyArguments(current, message, crypto.randomUUID()))
                    .then((sent) => sent && setAnswered(message))
            }
            pendingReply={reply.pending}
            replyError={reply.error}
            answered={answered}
            onAskFollowUp={
                app ? (text) => void app.sendMessage({ role: 'user', content: [{ type: 'text', text }] }) : undefined
            }
        />
    )
}

export function AgentOperationApp({ variant }: { variant: AgentOperationVariant }): ReactElement {
    return (
        <AppWrapper<AgentOperation> appName="PostHog Agent">
            {({ data, app }) => <AgentOperationContent data={data!} app={app} variant={variant} />}
        </AppWrapper>
    )
}
