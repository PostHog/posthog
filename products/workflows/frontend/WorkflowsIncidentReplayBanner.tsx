import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowsIncidentReplayLogic } from './workflowsIncidentReplayLogic'

// Mirrors the server-side HOG_INVOCATION_RERUN_MAX_COUNT default: one rerun request
// queues at most this many invocations, so larger workflows need a second pass.
const RERUN_MAX_COUNT_PER_REQUEST = 10000

export function WorkflowsIncidentReplayBanner(): JSX.Element | null {
    const { showBanner, affectedWorkflows, replayStatusById, currentProjectId } =
        useValues(workflowsIncidentReplayLogic)
    const { replayWorkflow } = useActions(workflowsIncidentReplayLogic)

    if (!showBanner) {
        return null
    }

    const hasLargeWorkflow = affectedWorkflows.some((workflow) => workflow.failedCount > RERUN_MAX_COUNT_PER_REQUEST)

    return (
        <LemonBanner
            type="warning"
            // Per project: without the suffix, dismissing in one project hides the recovery
            // path in every other project this browser visits.
            dismissKey={`workflows-incident-replay-2026-08-17-${currentProjectId}`}
            data-attr="workflows-incident-replay-banner"
        >
            <div className="flex flex-col gap-2">
                <div>
                    Some of your workflow emails failed to send between August 17 and August 18 (UTC) because of an
                    incident on our side. You can replay the failed sends for each affected workflow below. Replaying
                    only re-runs what failed during that period.
                    {hasLargeWorkflow ? (
                        <>
                            {' '}
                            A replay covers up to 10,000 failed sends per run. For workflows with more, replay again
                            after the first run finishes to send the rest.
                        </>
                    ) : null}
                </div>
                <ul className="flex flex-col gap-1">
                    {affectedWorkflows.map((workflow) => {
                        const status = replayStatusById[workflow.id]
                        return (
                            <li key={workflow.id} className="flex items-center gap-2">
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Workflow}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={workflow.userAccessLevel ?? undefined}
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        data-attr="workflows-incident-replay-button"
                                        loading={status === 'pending'}
                                        disabledReason={
                                            status === 'queued'
                                                ? 'Replay queued. Failed sends are being retried. Refresh the page to replay again once it finishes.'
                                                : undefined
                                        }
                                        onClick={() => replayWorkflow(workflow.id)}
                                    >
                                        {status === 'queued' ? 'Replay queued' : 'Replay failed sends'}
                                    </LemonButton>
                                </AccessControlAction>
                                <LemonButton size="xsmall" to={urls.workflow(workflow.id, 'workflow')}>
                                    {workflow.name}
                                </LemonButton>
                                <span className="text-secondary">
                                    {workflow.failedCount} failed {workflow.failedCount === 1 ? 'send' : 'sends'}
                                </span>
                            </li>
                        )
                    })}
                </ul>
            </div>
        </LemonBanner>
    )
}
