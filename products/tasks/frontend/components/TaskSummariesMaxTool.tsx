import { useActions } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { MaxTool } from 'scenes/max/MaxTool'
import { maxLogic } from 'scenes/max/maxLogic'

export function TaskSummariesMaxTool(): JSX.Element | null {
    const isEnabled = useFeatureFlag('TASK_SUMMARIES')

    const { setQuestion, focusInput, startNewConversation } = useActions(maxLogic)

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
