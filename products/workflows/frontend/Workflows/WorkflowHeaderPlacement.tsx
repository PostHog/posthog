import { useValues } from 'kea'

import { hogFlowEditorLogic } from './hogflows/hogFlowEditorLogic'
import type { WorkflowLogicProps } from './workflowLogic'

/** Tells the scene whether the editor carries the workflow header in its own bar. */
export function WorkflowHeaderPlacement({
    logicProps,
    children,
}: {
    logicProps: WorkflowLogicProps
    children: (showsHeaderInWorkflowBar: boolean) => JSX.Element
}): JSX.Element {
    const { showsHeaderInWorkflowBar } = useValues(hogFlowEditorLogic(logicProps))
    return children(showsHeaderInWorkflowBar)
}
