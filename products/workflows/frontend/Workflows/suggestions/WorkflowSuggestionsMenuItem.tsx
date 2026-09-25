import { useActions, useValues } from 'kea'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { SceneMenuBarCheckboxItem } from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsMenuItem({ id }: { id: string }): JSX.Element {
    const { optimisationEnabled, optimisationLoading, optimisationUnreadable } = useValues(
        workflowProposalsLogic({ id })
    )
    const { setOptimisationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel, workflow } = useValues(workflowLogic({ id }))
    const notLive = !!workflow && workflow.status !== 'active'

    // A viewer cannot flip it, so the item is inert instead of a request that ends in an error toast.
    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor,
        workflowUserAccessLevel ?? undefined
    )

    return (
        <SceneMenuBarCheckboxItem
            checked={optimisationEnabled}
            disabled={optimisationLoading || optimisationUnreadable || !!accessDisabledReason || notLive}
            onCheckedChange={(checked) => setOptimisationEnabled(checked)}
            data-attr="workflow-menubar-suggest-improvements"
        >
            Suggest improvements
        </SceneMenuBarCheckboxItem>
    )
}
