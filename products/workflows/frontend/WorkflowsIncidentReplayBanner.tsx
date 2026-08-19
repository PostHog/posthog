import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { workflowsIncidentReplayLogic } from './workflowsIncidentReplayLogic'

export function WorkflowsIncidentReplayBanner(): JSX.Element | null {
    const { showBanner, affectedWorkflows, replayStatusById } = useValues(workflowsIncidentReplayLogic)
    const { replayWorkflow } = useActions(workflowsIncidentReplayLogic)

    if (!showBanner) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            dismissKey="workflows-incident-replay-2026-08-17"
            data-attr="workflows-incident-replay-banner"
        >
            <div className="flex flex-col gap-2">
                <div>
                    Some of your workflow emails failed to send between August 17 and August 18 (UTC) because of an
                    incident on our side. You can replay the failed sends for each affected workflow below. Replaying
                    only re-runs what failed during that period.
                </div>
                <ul className="flex flex-col gap-1">
                    {affectedWorkflows.map((workflow) => {
                        const status = replayStatusById[workflow.id]
                        return (
                            <li key={workflow.id} className="flex items-center gap-2">
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    data-attr="workflows-incident-replay-button"
                                    loading={status === 'pending'}
                                    disabledReason={
                                        status === 'queued'
                                            ? 'Replay queued. Failed sends are being retried.'
                                            : undefined
                                    }
                                    onClick={() => replayWorkflow(workflow.id)}
                                >
                                    {status === 'queued' ? 'Replay queued' : 'Replay failed sends'}
                                </LemonButton>
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
