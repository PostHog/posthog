import { useActions, useValues } from 'kea'

import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsSwitch({ id }: { id: string }): JSX.Element {
    const { optimisationEnabled, optimisationLoading } = useValues(workflowProposalsLogic({ id }))
    const { setOptimisationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel, originalWorkflow } = useValues(workflowLogic({ id }))
    // A draft or archived workflow cannot be opted in; the switch stays visible and says why.
    const notLiveReason =
        originalWorkflow && originalWorkflow.status !== 'active'
            ? 'Suggestions need a live workflow. Enable it first.'
            : undefined

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={workflowUserAccessLevel ?? undefined}
        >
            {({ disabledReason }) => {
                const reason = disabledReason ?? notLiveReason
                // LemonSwitch's own tooltip covers only the knob, so the reason wraps the whole control.
                return (
                    <Tooltip title={reason}>
                        <div className="flex items-center">
                            <LemonSwitch
                                bordered
                                label="Suggest improvements"
                                checked={optimisationEnabled}
                                disabled={optimisationLoading || !!reason}
                                onChange={(checked) => setOptimisationEnabled(checked)}
                                data-attr="workflow-suggestions-enable"
                            />
                        </div>
                    </Tooltip>
                )
            }}
        </AccessControlAction>
    )
}
