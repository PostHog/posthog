import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import type { AgentOperation } from '../../tools/posthogAgent/operations'
import { AgentOperationView, isTerminal } from '../components/AgentOperationView'
import { AppWrapper } from '../components/AppWrapper'
import { useToolPolling } from '../hooks/useToolPolling'

function PostHogAgentRunContent({ data, app }: { data: AgentOperation; app: App | null }): JSX.Element {
    const {
        data: operation,
        error,
        setData,
    } = useToolPolling<AgentOperation>({
        app,
        initialData: data,
        toolName: 'posthog-agent-status',
        getArguments: (op) => ({
            operation_id: op.id,
            project_id: op.project.id,
            cursor: op.cursor,
            wait_seconds: 0,
        }),
        isDone: isTerminal,
        getIntervalSeconds: (op) => op.retry_after_seconds,
    })
    const [cancelling, setCancelling] = useState(false)
    const [cancelError, setCancelError] = useState<string | null>(null)

    const current = operation ?? data

    const handleCancel = useCallback(async () => {
        if (!app || cancelling) {
            return
        }
        setCancelling(true)
        setCancelError(null)
        try {
            const result = await app.callServerTool({
                name: 'posthog-agent-cancel',
                arguments: { operation_id: current.id, project_id: current.project.id },
            })
            if (result.isError || !result.structuredContent) {
                const text = result.content?.find((c) => c.type === 'text')
                setCancelError(text && 'text' in text ? text.text : 'Could not cancel the operation.')
            } else {
                setData(result.structuredContent as unknown as AgentOperation)
            }
        } catch (e) {
            setCancelError(e instanceof Error ? e.message : String(e))
        } finally {
            setCancelling(false)
        }
    }, [app, cancelling, current.id, current.project.id, setData])

    return (
        <AgentOperationView
            operation={current}
            onOpenLink={(url) => (app ? void app.openLink({ url }) : window.open(url, '_blank', 'noopener,noreferrer'))}
            canControl={!!app}
            pollError={error}
            onCancel={() => void handleCancel()}
            cancelling={cancelling}
            cancelError={cancelError}
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
