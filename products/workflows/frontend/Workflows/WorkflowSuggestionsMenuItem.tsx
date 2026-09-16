import { useActions, useValues } from 'kea'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { SceneMenuBarCheckboxItem } from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from './workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsMenuItem({ id }: { id: string }): JSX.Element {
    const { optimisationEnabled, optimisationLoading, optimisationUnreadable } = useValues(
        workflowProposalsLogic({ id })
    )
    const { setOptimisationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel } = useValues(workflowLogic({ id }))

    // Flipping it is a workflow write, so a viewer gets an inert item rather than a request that
    // can only end in an error toast.
    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor,
        workflowUserAccessLevel ?? undefined
    )

    return (
        <SceneMenuBarCheckboxItem
            checked={optimisationEnabled}
            disabled={optimisationLoading || optimisationUnreadable || !!accessDisabledReason}
            onCheckedChange={(checked) => setOptimisationEnabled(checked)}
            data-attr="workflow-menubar-suggest-improvements"
        >
            Suggest improvements
        </SceneMenuBarCheckboxItem>
    )
}
