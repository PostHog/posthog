import '../../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback } from 'react'
import { createRoot } from 'react-dom/client'

import {
    type ErrorIssueData,
    type ErrorIssueListData,
    ErrorIssueListView,
} from 'products/error_tracking/frontend/mcp-apps'

import { AppWrapper } from '../../components/AppWrapper'

function ErrorIssueListApp(): JSX.Element {
    return (
        <AppWrapper<ErrorIssueListData> appName="PostHog Error Issues">
            {({ data, app }) => <ErrorIssueListContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function ErrorIssueListContent({ data, app }: { data: ErrorIssueListData; app: App | null }): JSX.Element {
    const fallbackToChat = useCallback(
        (name: string) => {
            app?.sendMessage({
                role: 'user',
                content: [{ type: 'text', text: `Show me the details for error issue "${name}"` }],
            })
        },
        [app]
    )

    const handleClick = useCallback(
        async (issue: ErrorIssueData): Promise<ErrorIssueData | null> => {
            if (!app) {
                fallbackToChat(issue.name)
                return null
            }
            try {
                const result = await app.callServerTool({
                    name: 'error-tracking-issues-retrieve',
                    arguments: { id: issue.id },
                })
                if (result.isError || !result.structuredContent) {
                    fallbackToChat(issue.name)
                    return null
                }
                return result.structuredContent as unknown as ErrorIssueData
            } catch {
                fallbackToChat(issue.name)
                return null
            }
        },
        [app, fallbackToChat]
    )

    return <ErrorIssueListView data={data} onIssueClick={handleClick} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ErrorIssueListApp />)
}
