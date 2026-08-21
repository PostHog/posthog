import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import type { ReactElement } from 'react'
import { createRoot } from 'react-dom/client'
import { z } from 'zod'

import { Button, Card, CardContent } from '@posthog/quill'

import { AppWrapper } from '../components/AppWrapper'
import type { ShowAction, ShowActionsData } from './task-show-actions-links'

/**
 * A PostHog extension to the MCP Apps protocol. The spec's `ui/open-link` would
 * have this sandbox choose the URL the host then opens; sending the verb instead
 * leaves the host deciding what a click can reach, and lets it pick the deep-link
 * scheme its own build registered.
 */
const OPEN_ACTION_METHOD = 'posthog/open-action'

const OpenActionResultSchema = z.object({})

type AppRequest = Parameters<App['request']>[0]

function sendAction(app: App | null, action: ShowAction): void {
    if (!app) {
        return
    }
    void app.request(
        { method: OPEN_ACTION_METHOD, params: { action } } as unknown as AppRequest,
        OpenActionResultSchema
    )
}

interface TaskShowActionsCardProps {
    actions: ShowAction[]
    onAction: (action: ShowAction) => void
}

export function TaskShowActionsCard({ actions, onAction }: TaskShowActionsCardProps): ReactElement {
    if (actions.length === 0) {
        return (
            <Card className="m-4">
                <CardContent className="p-4">
                    <p className="text-sm text-muted-foreground">No actions to show.</p>
                </CardContent>
            </Card>
        )
    }

    return (
        <Card className="m-4">
            <CardContent className="flex flex-wrap gap-2 p-4">
                {actions.map((action, index) => (
                    <Button key={`${index}-${action.label}`} variant="outline" onClick={() => onAction(action)}>
                        {action.label}
                    </Button>
                ))}
            </CardContent>
        </Card>
    )
}

function TaskShowActionsApp(): ReactElement {
    return (
        <AppWrapper<ShowActionsData> appName="PostHog Actions">
            {({ data, app }) => (
                <TaskShowActionsCard actions={data?.actions ?? []} onAction={(action) => sendAction(app, action)} />
            )}
        </AppWrapper>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<TaskShowActionsApp />)
}
