import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCode, IconInfo, IconWrench } from '@posthog/icons'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { GitMetadataParser } from 'lib/components/Git/gitMetadataParser'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { useStacktraceDisplay } from '../../../../hooks/use-stacktrace-display'
import { buildExplainPrompt, buildFixPrompt } from '../../aiPrompts'

export interface StackTraceActionsProps {
    issue: ErrorTrackingRelationalIssue
}

export function StackTraceActions({ issue }: StackTraceActionsProps): JSX.Element {
    const { exceptionList, release } = useValues(errorPropertiesLogic)
    const { copyableStacktraceText, ready, stacktraceText } = useStacktraceDisplay()

    return (
        <div className="flex items-center gap-1">
            {exceptionList.length > 0 && ready && (
                <AgentPromptButton
                    storageKey="error-tracking-issue"
                    defaultActionKey="fix"
                    defaultAgentKey="clipboard"
                    size="sm"
                    data-attr="error-tracking-fix-with-ai"
                    repository={GitMetadataParser.getGitHubRepositorySlug(release?.metadata?.git?.remote_url)}
                    actions={[
                        {
                            key: 'fix',
                            label: 'Fix prompt',
                            icon: <IconWrench />,
                            buildPrompt: () => buildFixPrompt(stacktraceText, issue.id),
                        },
                        {
                            key: 'explain',
                            label: 'Explain prompt',
                            icon: <IconInfo />,
                            buildPrompt: () => buildExplainPrompt(stacktraceText, issue.id),
                        },
                        {
                            key: 'stacktrace',
                            label: 'Stack trace',
                            icon: <IconCode />,
                            buildPrompt: () => copyableStacktraceText,
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
