import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback } from 'react'
import { createRoot } from 'react-dom/client'

import { type SurveyData, type SurveyListData, SurveyListView } from 'products/surveys/frontend/mcp-apps'

import { AppWrapper } from '../components/AppWrapper'

function SurveyListApp(): JSX.Element {
    return (
        <AppWrapper<SurveyListData> appName="PostHog Surveys">
            {({ data, app }) => <SurveyListContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function SurveyListContent({ data, app }: { data: SurveyListData; app: App | null }): JSX.Element {
    const fallbackToChat = useCallback(
        (name: string) => {
            app?.sendMessage({
                role: 'user',
                content: [{ type: 'text', text: `Show me the details for survey "${name}"` }],
            })
        },
        [app]
    )

    const handleClick = useCallback(
        async (survey: SurveyData): Promise<SurveyData | null> => {
            if (!app) {
                fallbackToChat(survey.name)
                return null
            }
            try {
                const result = await app.callServerTool({
                    name: 'survey-get',
                    arguments: { surveyId: survey.id },
                })
                if (result.isError || !result.structuredContent) {
                    fallbackToChat(survey.name)
                    return null
                }
                return result.structuredContent as unknown as SurveyData
            } catch {
                fallbackToChat(survey.name)
                return null
            }
        },
        [app, fallbackToChat]
    )

    return <SurveyListView data={data} onSurveyClick={handleClick} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<SurveyListApp />)
}
