import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsPanelToggle({ id }: { id: string }): JSX.Element {
    const { optimizationEnabled, optimizationLoading, optimizationUnreadable } = useValues(
        workflowProposalsLogic({ id })
    )
    const { setOptimizationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel, workflow } = useValues(workflowLogic({ id }))
    // Only turning it on needs a live workflow, so an archived workflow can still be switched off.
    const notLiveReason =
        !!workflow && workflow.status !== 'active' && !optimizationEnabled
            ? 'Suggestions need a live workflow. Enable it first.'
            : undefined

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={workflowUserAccessLevel ?? undefined}
        >
            {({ disabledReason }) => (
                <LemonSwitch
                    id="workflow-self-optimization"
                    data-attr="workflow-suggest-improvements"
                    className="px-2 py-1"
                    checked={optimizationEnabled}
                    onChange={(checked) => setOptimizationEnabled(checked)}
                    // A failed read must not show "off" for a workflow that may be on.
                    disabled={optimizationLoading || optimizationUnreadable || !!disabledReason || !!notLiveReason}
                    tooltip={
                        disabledReason ??
                        notLiveReason ??
                        (optimizationUnreadable
                            ? 'Could not read whether suggestions are on for this workflow. Reload the page to try again.'
                            : 'PostHog reads how this workflow performs and suggests changes for you to review. Nothing reaches anyone until you approve a suggestion and publish it.')
                    }
                    fullWidth
                    label="Suggest improvements"
                />
            )}
        </AccessControlAction>
    )
}
