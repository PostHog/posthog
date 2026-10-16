import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { type WorkflowSendingRulesData, WorkflowSendingRulesView } from 'products/workflows/mcp/apps'

import { AppWrapper } from '../components/AppWrapper'

const SAVE_FAILED = "We couldn't save the sending rules. Only project admins can change them."

function WorkflowSendingRulesApp(): JSX.Element {
    return (
        <AppWrapper<WorkflowSendingRulesData> appName="PostHog Sending Rules">
            {({ data, app }) => (data ? <WorkflowSendingRulesContent initial={data} app={app} /> : null)}
        </AppWrapper>
    )
}

function WorkflowSendingRulesContent({
    initial,
    app,
}: {
    initial: WorkflowSendingRulesData
    app: App | null
}): JSX.Element {
    const [data, setData] = useState(initial)
    const [saving, setSaving] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const save = useCallback(
        async (changes: Partial<WorkflowSendingRulesData>, chatRequest: string): Promise<void> => {
            if (!app) {
                return
            }
            setSaving(true)
            setError(null)
            try {
                const result = await app.callServerTool({ name: 'workflows-sending-rules-update', arguments: changes })
                const saved = result.structuredContent as unknown as WorkflowSendingRulesData | undefined
                if (result.isError || !saved) {
                    setError(SAVE_FAILED)
                } else {
                    setData(saved)
                }
            } catch {
                // The host cannot call tools from an app, so the agent makes the change from the chat instead.
                app.sendMessage({ role: 'user', content: [{ type: 'text', text: chatRequest }] })
            } finally {
                setSaving(false)
            }
        },
        [app]
    )

    return (
        <WorkflowSendingRulesView
            data={data}
            saving={saving}
            error={error}
            onApplyRecommendedCap={
                app
                    ? () =>
                          void save(
                              { marketing_frequency_cap_max_messages: 1, marketing_frequency_cap_window_days: 2 },
                              'Set the frequency cap to 1 marketing email every 2 days with workflows-sending-rules-update.'
                          )
                    : undefined
            }
            onEngagementEventsChange={
                app
                    ? (enabled) =>
                          void save(
                              { capture_workflows_engagement_events: enabled },
                              `Turn ${enabled ? 'on' : 'off'} email engagement events with workflows-sending-rules-update.`
                          )
                    : undefined
            }
        />
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<WorkflowSendingRulesApp />)
}
