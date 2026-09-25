import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsPanelToggle({ id }: { id: string }): JSX.Element {
    const { optimisationEnabled, optimisationLoading, optimisationUnreadable } = useValues(
        workflowProposalsLogic({ id })
    )
    const { setOptimisationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel, workflow } = useValues(workflowLogic({ id }))
    const notLiveReason =
        !!workflow && workflow.status !== 'active' ? 'Suggestions need a live workflow. Enable it first.' : undefined

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={workflowUserAccessLevel ?? undefined}
        >
            {({ disabledReason }) => (
                <LemonSwitch
                    id="workflow-self-optimising"
                    data-attr="workflow-suggest-improvements"
                    className="px-2 py-1"
                    checked={optimisationEnabled}
                    onChange={(checked) => setOptimisationEnabled(checked)}
                    // A failed read must not show "off" for a workflow that may be on.
                    disabled={optimisationLoading || optimisationUnreadable || !!disabledReason || !!notLiveReason}
                    tooltip={
                        disabledReason ??
                        notLiveReason ??
                        (optimisationUnreadable
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
