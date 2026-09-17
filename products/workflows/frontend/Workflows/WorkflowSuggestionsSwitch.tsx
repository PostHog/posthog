import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from './workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

/** The per-workflow opt-in, as it appears on the Suggestions tab in both its states. */
export function WorkflowSuggestionsSwitch({ id }: { id: string }): JSX.Element {
    const { optimisationEnabled, optimisationLoading } = useValues(workflowProposalsLogic({ id }))
    const { setOptimisationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel, originalWorkflow } = useValues(workflowLogic({ id }))
    // A draft has no sends to judge and an archived workflow is done, so the switch stays visible
    // but says why it cannot be turned on. The server refuses the opt-in for those states too.
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
            {({ disabledReason }) => (
                <LemonSwitch
                    bordered
                    label="Suggest improvements"
                    checked={optimisationEnabled}
                    disabled={optimisationLoading}
                    disabledReason={disabledReason ?? notLiveReason}
                    onChange={(checked) => setOptimisationEnabled(checked)}
                    data-attr="workflow-suggestions-enable"
                />
            )}
        </AccessControlAction>
    )
}
