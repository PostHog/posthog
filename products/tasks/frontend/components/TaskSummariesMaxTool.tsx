import { useActions, useValues } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { maxLogic } from 'scenes/max/maxLogic'

import { tasksLogic } from '../tasksLogic'
import { OriginProduct, TaskStatus } from './../types'

export function TaskSummariesMaxTool(): JSX.Element | null {
    const isEnabled = useFeatureFlag('TASK_SUMMARIES')

    const { createTask } = useActions(tasksLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const tasksEnabled = !!featureFlags['tasks']

    const { setQuestion, focusInput, startNewConversation } = useActions(maxLogic)

    const initialPrompt =
        'Use the session_summarization tool to summarize all recent session recordings in the last 30 days and identify the top UX issues and recurring patterns. Focus on actionable fixes. Return a structured JSON artifact via tool result containing a `patterns` array (with `pattern_name`, `pattern_description`, `severity`, `stats`) and an optional `notebook_id`. Do not answer without calling the tool.'

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
                callback={async (toolOutput: any) => {
                    try {
                        lemonToast.success('Max session summary received')
                    } catch {}
                    try {
                        if (!tasksEnabled) {
                            lemonToast.warning('Tasks flag is disabled – not creating tasks')
                            return
                        }
                        let payload = toolOutput
                        if (typeof payload === 'string') {
                            try {
                                payload = JSON.parse(payload)
                            } catch {}
                        }
                        const patterns = payload?.patterns || payload?.result?.patterns
                        if (!Array.isArray(patterns) || patterns.length === 0) {
                            lemonToast.info('No patterns returned from Max')
                            return
                        }
                        for (const pattern of patterns) {
                            const title: string = `[Replay] ${pattern.pattern_name}`
                            const severity: string = pattern?.severity?.value || pattern?.severity || 'unknown'
                            const sessionsAffected: number | undefined = pattern?.stats?.sessions_affected
                            const failureRate: number | undefined =
                                pattern?.stats && typeof pattern.stats.segments_success_ratio === 'number'
                                    ? Math.round((1 - pattern.stats.segments_success_ratio) * 100)
                                    : undefined
                            const notebookHint = payload?.notebook_id ? `\n\nNotebook: ${payload.notebook_id}` : ''
                            const meta = [
                                `Severity: ${severity}`,
                                sessionsAffected != null ? `Sessions affected: ${sessionsAffected}` : undefined,
                                failureRate != null ? `Estimated failure rate: ${failureRate}%` : undefined,
                            ]
                                .filter(Boolean)
                                .join(' | ')
                            const description: string = `${pattern.pattern_description}\n\n${meta}${notebookHint}`

                            await createTask({
                                title,
                                description,
                                status: TaskStatus.BACKLOG,
                                origin_product: OriginProduct.USER_CREATED,
                            })
                        }
                        lemonToast.success('Created tasks from Max summary')
                    } catch {
                        lemonToast.error('Error creating tasks from Max summary')
                    }
                }}
                position="top-right"
            >
                <h2 className="text-xl font-semibold">Kanban Board</h2>
            </MaxTool>
        </div>
    )
}
