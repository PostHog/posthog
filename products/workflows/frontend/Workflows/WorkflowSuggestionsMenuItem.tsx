import { useActions, useValues } from 'kea'

import { SceneMenuBarCheckboxItem } from '~/layout/scenes/components/SceneMenuBar'

import { workflowProposalsLogic } from './workflowProposalsLogic'

export function WorkflowSuggestionsMenuItem({ id }: { id: string }): JSX.Element {
    const { optimisationEnabled, optimisationLoading } = useValues(workflowProposalsLogic({ id }))
    const { setOptimisationEnabled } = useActions(workflowProposalsLogic({ id }))

    return (
        <SceneMenuBarCheckboxItem
            checked={optimisationEnabled}
            disabled={optimisationLoading}
            onCheckedChange={(checked) => setOptimisationEnabled(checked)}
            data-attr="workflow-menubar-suggest-improvements"
        >
            Suggest improvements
        </SceneMenuBarCheckboxItem>
    )
}
