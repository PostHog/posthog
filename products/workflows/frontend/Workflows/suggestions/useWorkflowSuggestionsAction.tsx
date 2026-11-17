import { useActions, useValues } from 'kea'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowLogic } from '../workflowLogic'
import { workflowProposalsLogic } from './workflowProposalsLogic'

/** The "Suggest improvements" toggle. It loads the workflow's proposals, so call it only where suggestions are available. */
export function useWorkflowSuggestionsAction(
    id: string,
    { group = 'view', section }: { group?: SceneActionGroup; section?: string } = {}
): SceneAction {
    const { optimizationEnabled, optimizationLoading, optimizationUnreadable, turnOnDisabledReason } = useValues(
        workflowProposalsLogic({ id })
    )
    const { setOptimizationEnabled } = useActions(workflowProposalsLogic({ id }))
    const { workflowUserAccessLevel } = useValues(workflowLogic({ id }))

    // A viewer cannot flip it, so the item is inert instead of a request that ends in an error toast.
    const accessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Workflow,
        AccessControlLevel.Editor,
        workflowUserAccessLevel ?? undefined
    )

    return {
        group,
        section,
        type: 'checkbox',
        id: 'workflow-menubar-suggest-improvements',
        label: 'Suggest improvements',
        checked: optimizationEnabled,
        disabledReason:
            accessDisabledReason ??
            turnOnDisabledReason ??
            (optimizationLoading
                ? 'Loading suggestion settings'
                : optimizationUnreadable
                  ? "Couldn't load suggestion settings"
                  : undefined),
        onCheckedChange: (checked) => setOptimizationEnabled(checked),
    }
}
