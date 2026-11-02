import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback } from 'react'
import { createRoot } from 'react-dom/client'

import { type WorkflowData, WorkflowView } from 'products/workflows/mcp/apps'

import { AppWrapper } from '../components/AppWrapper'
import { parseToolResultContent } from '../hooks/useToolResult'

function WorkflowApp(): JSX.Element {
    return (
        <AppWrapper<WorkflowData> appName="PostHog Workflow">
            {({ data, app }) => (data ? <WorkflowContent workflow={data} app={app} /> : null)}
        </AppWrapper>
    )
}

function WorkflowContent({ workflow, app }: { workflow: WorkflowData; app: App | null }): JSX.Element {
    const loadFullWorkflow = useCallback(async (): Promise<WorkflowData | null> => {
        if (!app) {
            return null
        }
        try {
            const result = await app.callServerTool({ name: 'workflows-get', arguments: { id: workflow.id } })
            return result.isError ? null : parseToolResultContent<WorkflowData>(result.structuredContent, result._meta)
        } catch {
            return null
        }
    }, [app, workflow.id])

    return <WorkflowView workflow={workflow} loadFullWorkflow={loadFullWorkflow} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<WorkflowApp />)
}
