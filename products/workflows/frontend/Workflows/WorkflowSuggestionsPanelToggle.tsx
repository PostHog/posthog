import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from './workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsPanelToggle({ id }: { id: string }): JSX.Element {
    const { optimisationEnabled, optimisationLoading, optimisationUnreadable } = useValues(
        workflowProposalsLogic({ id })
    )
    const { setOptimisationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel } = useValues(workflowLogic({ id }))

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
                    // A read that failed leaves this switch showing "off" for a workflow that may be
                    // on, so it stays inert and says so until an answer arrives.
                    disabled={optimisationLoading || optimisationUnreadable || !!disabledReason}
                    tooltip={
                        disabledReason ??
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
