import { useActions, useValues } from 'kea'

import { LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsSwitch({ id }: { id: string }): JSX.Element {
    const { optimizationEnabled, optimizationLoading, optimizationUnreadable, turnOnDisabledReason } = useValues(
        workflowProposalsLogic({ id })
    )
    const { setOptimizationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel } = useValues(workflowLogic({ id }))

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Workflow}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={workflowUserAccessLevel ?? undefined}
        >
            {({ disabledReason }) => {
                // A failed read leaves the switch showing a default, so acting on it would write from a state
                // nobody read. The panel toggle refuses the same way.
                const unreadableReason = optimizationUnreadable
                    ? 'Could not read whether suggestions are on for this workflow. Reload the page to try again.'
                    : undefined
                const reason = disabledReason ?? turnOnDisabledReason ?? unreadableReason
                // LemonSwitch's own tooltip covers only the knob, so the reason wraps the whole control.
                return (
                    <Tooltip title={reason}>
                        <div className="flex items-center">
                            <LemonSwitch
                                bordered
                                label="Suggest improvements"
                                checked={optimizationEnabled}
                                disabled={optimizationLoading || !!reason}
                                onChange={(checked) => setOptimizationEnabled(checked)}
                                data-attr="workflow-suggestions-enable"
                            />
                        </div>
                    </Tooltip>
                )
            }}
        </AccessControlAction>
    )
}
