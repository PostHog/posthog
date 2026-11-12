import { useActions, useMountedLogic, useValues } from 'kea'

import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { pagePerformanceLogic } from 'scenes/web-analytics/pagePerformanceLogic'

import { AiAssistantList } from './AiAssistantList'
import { searchAndAiAssistantsLogic } from './searchAndAiAssistantsLogic'

export function AiAssistantsCard(): JSX.Element {
    const { props } = useMountedLogic(pagePerformanceLogic)
    const { assistants, assistantsLoading, assistantsFailed } = useValues(searchAndAiAssistantsLogic(props))
    const { loadAssistants } = useActions(searchAndAiAssistantsLogic(props))

    return (
        <PagePerformanceCard title="By assistant" className="flex-1 min-w-0">
            <AiAssistantList
                rows={assistants}
                loading={assistantsLoading}
                emptyText="No visitors arrived from an AI assistant in this period."
                failed={assistantsFailed}
                onRetry={() => loadAssistants({})}
            />
        </PagePerformanceCard>
    )
}
