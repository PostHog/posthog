import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconInfo, IconWrench } from '@posthog/icons'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { useStacktraceDisplay } from '../../../../hooks/use-stacktrace-display'
import { buildExplainPrompt, buildFixPrompt } from '../../aiPrompts'

export interface StackTraceActionsProps {
    issue: ErrorTrackingRelationalIssue
}

export function StackTraceActions({ issue }: StackTraceActionsProps): JSX.Element {
    const { exceptionList } = useValues(errorPropertiesLogic)
    const showFixButton = hasResolvedStackFrames(exceptionList)
    const { stacktraceText } = useStacktraceDisplay()

    return (
        <div className="flex items-center gap-1">
            {showFixButton && (
                <AgentPromptButton
                    storageKey="error-tracking-issue"
                    size="sm"
                    data-attr="error-tracking-fix-with-ai"
                    actions={[
                        {
                            key: 'fix',
                            label: 'Fix',
                            icon: <IconWrench />,
                            buildPrompt: () => buildFixPrompt(stacktraceText, issue.id),
                        },
                        {
                            key: 'explain',
                            label: 'Explain',
                            icon: <IconInfo />,
                            buildPrompt: () => buildExplainPrompt(stacktraceText, issue.id),
                        },
                    ]}
                    onRun={({ actionKey, agentKey }) =>
                        posthog.capture('error_tracking_prompt_used', {
                            issue_id: issue.id,
                            mode: actionKey,
                            agent: agentKey,
                        })
                    }
                />
            )}
        </div>
    )
}

// Helper function to check if any exception has resolved stack frames
function hasResolvedStackFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some((exception) => {
        if (exception.stacktrace?.type === 'resolved' && exception.stacktrace?.frames) {
            return exception.stacktrace.frames.some((frame) => frame.resolved)
        }
        return false
    })
}
