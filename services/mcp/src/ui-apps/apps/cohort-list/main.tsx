import '../../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback } from 'react'
import { createRoot } from 'react-dom/client'

import { type CohortData, type CohortListData, CohortListView } from 'products/cohorts/frontend/mcp-apps'

import { AppWrapper } from '../../components/AppWrapper'

function CohortListApp(): JSX.Element {
    return (
        <AppWrapper<CohortListData> appName="PostHog Cohorts">
            {({ data, app }) => <CohortListContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function CohortListContent({ data, app }: { data: CohortListData; app: App | null }): JSX.Element {
    const fallbackToChat = useCallback(
        (name: string) => {
            app?.sendMessage({
                role: 'user',
                content: [{ type: 'text', text: `Show me the details for cohort "${name}"` }],
            })
        },
        [app]
    )

    const handleClick = useCallback(
        async (cohort: CohortData): Promise<CohortData | null> => {
            if (!app) {
                fallbackToChat(cohort.name)
                return null
            }
            try {
                const result = await app.callServerTool({
                    name: 'cohorts-retrieve',
                    arguments: { id: cohort.id },
                })
                if (result.isError || !result.structuredContent) {
                    fallbackToChat(cohort.name)
                    return null
                }
                return result.structuredContent as unknown as CohortData
            } catch {
                fallbackToChat(cohort.name)
                return null
            }
        },
        [app, fallbackToChat]
    )

    return <CohortListView data={data} onCohortClick={handleClick} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<CohortListApp />)
}
