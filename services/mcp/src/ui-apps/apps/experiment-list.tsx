import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback } from 'react'
import { createRoot } from 'react-dom/client'

import {
    type ExperimentData,
    type ExperimentListData,
    ExperimentListView,
} from 'products/experiments/frontend/mcp-apps'

import { AppWrapper } from '../components/AppWrapper'

function ExperimentListApp(): JSX.Element {
    return (
        <AppWrapper<ExperimentListData> appName="PostHog Experiments">
            {({ data, app }) => <ExperimentListContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function ExperimentListContent({ data, app }: { data: ExperimentListData; app: App | null }): JSX.Element {
    const fallbackToChat = useCallback(
        (name: string) => {
            app?.sendMessage({
                role: 'user',
                content: [{ type: 'text', text: `Show me the details for experiment "${name}"` }],
            })
        },
        [app]
    )

    const handleClick = useCallback(
        async (experiment: ExperimentData): Promise<ExperimentData | null> => {
            if (!app) {
                fallbackToChat(experiment.name)
                return null
            }
            try {
                const result = await app.callServerTool({
                    name: 'experiment-get',
                    arguments: { experimentId: experiment.id },
                })
                if (result.isError || !result.structuredContent) {
                    fallbackToChat(experiment.name)
                    return null
                }
                return result.structuredContent as unknown as ExperimentData
            } catch {
                fallbackToChat(experiment.name)
                return null
            }
        },
        [app, fallbackToChat]
    )

    return <ExperimentListView data={data} onExperimentClick={handleClick} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<ExperimentListApp />)
}
