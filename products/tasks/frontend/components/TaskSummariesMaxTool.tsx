import { useActions } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { MaxTool } from 'scenes/max/MaxTool'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { maxLogic } from 'scenes/max/maxLogic'

export function TaskSummariesMaxTool(): JSX.Element | null {
    const isEnabled = useFeatureFlag('TASK_SUMMARIES')

    const { openSidePanelMax } = useActions(maxGlobalLogic)
    const { setQuestion, focusInput, startNewConversation } = useActions(maxLogic({ tabId: 'sidepanel' }))

    const initialPrompt =
        'Use the session_summarization tool to summarize all recent session recordings in the last 30 days. Focus on actionable fixes.'

    if (!isEnabled) {
        return null
    }

    return (
        <div className="relative">
            <MaxTool
                identifier="session_summarization"
                initialMaxPrompt={initialPrompt}
                onMaxOpen={() => {
                    openSidePanelMax()
                    startNewConversation()
                    setQuestion(initialPrompt)
                    focusInput()
                }}
                position="top-right"
            >
                <h2 className="text-xl font-semibold">Kanban Board</h2>
            </MaxTool>
        </div>
    )
}
