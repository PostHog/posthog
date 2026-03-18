import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback } from 'react'
import { createRoot } from 'react-dom/client'

import { type ActionData, type ActionListData, ActionListView } from 'products/actions/frontend/mcp-apps'

import { AppWrapper } from '../components/AppWrapper'

function ActionListApp(): JSX.Element {
    return (
        <AppWrapper<ActionListData> appName="PostHog Actions">
            {({ data, app }) => <ActionListContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function ActionListContent({ data, app }: { data: ActionListData; app: App | null }): JSX.Element {
    const fallbackToChat = useCallback(
        (name: string) => {
            app?.sendMessage({
                role: 'user',
                content: [{ type: 'text', text: `Show me the details for action "${name}"` }],
            })
        },
        [app]
    )

    const handleClick = useCallback(
        async (action: ActionData): Promise<ActionData | null> => {
            if (!app) {
                fallbackToChat(action.name)
                return null
            }
            try {
                const result = await app.callServerTool({
                    name: 'action-get',
                    arguments: { id: action.id },
                })
                if (result.isError || !result.structuredContent) {
                    fallbackToChat(action.name)
                    return null
                }
                return result.structuredContent as unknown as ActionData
            } catch {
                fallbackToChat(action.name)
                return null
            }
        },
        [app, fallbackToChat]
    )

    return <ActionListView data={data} onActionClick={handleClick} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ActionListApp />)
}
