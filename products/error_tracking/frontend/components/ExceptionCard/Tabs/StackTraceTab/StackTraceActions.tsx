import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCode, IconInfo, IconWrench } from '@posthog/icons'

import { AgentPromptButton } from 'lib/components/AgentPromptButton'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingRelease } from 'lib/components/Errors/types'

import { ErrorTrackingRelationalIssue } from '~/queries/schema/schema-general'

import { useStacktraceDisplay } from '../../../../hooks/use-stacktrace-display'
import { GitMetadataParser } from '../../../ReleasesPreview/gitMetadataParser'
import { buildExplainPrompt, buildFixPrompt } from '../../aiPrompts'

export interface StackTraceActionsProps {
    issue: ErrorTrackingRelationalIssue
}

function getReleaseRepository(release?: ErrorTrackingRelease | null): string | undefined {
    const git = release?.metadata?.git
    if (!git) {
        return undefined
    }
    if (git.repo_name) {
        return git.repo_name
    }
    const parsedRemoteUrl = git.remote_url ? GitMetadataParser.parseRemoteUrl(git.remote_url) : undefined
    return parsedRemoteUrl ? `${parsedRemoteUrl.owner}/${parsedRemoteUrl.repository}` : undefined
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
                    repository={getReleaseRepository(release)}
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
