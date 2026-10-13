import { useActions, useValues } from 'kea'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { SceneMenuBarCheckboxItem } from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsMenuItem({ id }: { id: string }): JSX.Element {
    const { optimizationEnabled, optimizationLoading, optimizationUnreadable } = useValues(
        workflowProposalsLogic({ id })
    )
    const { setOptimizationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel, workflow } = useValues(workflowLogic({ id }))
    // Only turning it on needs a live workflow; the server takes `enabled: false` either way. Blocking
    // both would strand an opted-in workflow opted in the moment it is archived.
    const notLive = !!workflow && workflow.status !== 'active' && !optimizationEnabled

    // A viewer cannot flip it, so the item is inert instead of a request that ends in an error toast.
    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor,
        workflowUserAccessLevel ?? undefined
    )

    return (
        <SceneMenuBarCheckboxItem
            checked={optimizationEnabled}
            disabled={optimizationLoading || optimizationUnreadable || !!accessDisabledReason || notLive}
            onCheckedChange={(checked) => setOptimizationEnabled(checked)}
            data-attr="workflow-menubar-suggest-improvements"
        >
            Suggest improvements
        </SceneMenuBarCheckboxItem>
    )
}
