import type { App } from '@modelcontextprotocol/ext-apps'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'

import {
    type AgentOperation,
    agentViewCancelArguments,
    agentViewReplyArguments,
    agentViewStatusArguments,
    formatAgentOperationText,
} from '../../tools/posthogAgent/operations'
import { useToolPolling } from '../hooks/useToolPolling'
import { parseToolResultContent } from '../hooks/useToolResult'
import { AgentOperationView, isTerminal } from './AgentOperationView'
import { AppWrapper } from './AppWrapper'

/** Calls an operation tool, then replaces the shown operation with the one it returns. */
function useOperationAction(
    app: App | null,
    setData: (operation: AgentOperation) => void,
    fallbackError: string,
    isHarmlessError: (text: string) => boolean = () => false
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
                const content = result.content?.find((c) => c.type === 'text')
                const text = content && 'text' in content ? content.text : fallbackError
                if (isHarmlessError(text)) {
                    return true
                }
                setError(text)
            } catch (e) {
                setError(e instanceof Error ? e.message : String(e))
            } finally {
                setPending(null)
            }
            return false
        },
        [app, pending, setData, fallbackError, isHarmlessError]
    )

    return { pending, error, run }
}

/** A clicked approval that another view or the chat answered first is not an error for the user. */
const isAlreadyAnswered = (text: string): boolean => /already answered/i.test(text)

/**
 * The chat may end its turn while the run continues. When the run ends while this view is open, give
 * the chat model the result, so the next message in the chat knows it.
 */
function useResultForChat(app: App | null, operation: AgentOperation): void {
    const sawRunning = useRef(!isTerminal(operation))
    useEffect(() => {
        if (!isTerminal(operation)) {
            sawRunning.current = true
            return
        }
        if (!app || !sawRunning.current) {
            return
        }
        sawRunning.current = false
        app.updateModelContext({
            content: [
                { type: 'text', text: `The PostHog Agent run finished.\n${formatAgentOperationText(operation)}` },
            ],
        }).catch(() => {})
    }, [app, operation])
}

function AgentOperationContent({ data, app }: { data: AgentOperation; app: App | null }): ReactElement {
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
    const cancel = useOperationAction(app, setData, 'Could not cancel the run. Try again.')
    const reply = useOperationAction(app, setData, 'Could not send your reply. Try again.', isAlreadyAnswered)
    const [answered, setAnswered] = useState<string | null>(null)
    const [answeredApprovalId, setAnsweredApprovalId] = useState<string | null>(null)

    const current = operation ?? data
    useResultForChat(app, current)

    return (
        <AgentOperationView
            operation={current}
            onOpenLink={(url) => (app ? void app.openLink({ url }) : window.open(url, '_blank', 'noopener,noreferrer'))}
            canControl={!!app}
            pollError={error}
            onCancel={() => void cancel.run('cancel', 'posthog-agent-cancel', agentViewCancelArguments(current))}
            cancelling={cancel.pending !== null}
            cancelError={cancel.error}
            onReply={(message) => {
                const approvalId = current.approval?.request_id ?? null
                void reply
                    .run(message, 'posthog-agent-reply', agentViewReplyArguments(current, message, crypto.randomUUID()))
                    .then((sent) => {
                        if (sent) {
                            setAnswered(message)
                            setAnsweredApprovalId(approvalId)
                        }
                    })
            }}
            pendingReply={reply.pending}
            replyError={reply.error}
            answered={answered}
            answeredApprovalId={answeredApprovalId}
            onAskFollowUp={
                app ? (text) => void app.sendMessage({ role: 'user', content: [{ type: 'text', text }] }) : undefined
            }
        />
    )
}

export function AgentOperationApp(): ReactElement {
    return (
        <AppWrapper<AgentOperation> appName="PostHog Agent">
            {({ data, app }) => <AgentOperationContent data={data!} app={app} />}
        </AppWrapper>
    )
}
