import { useMountedLogic } from 'kea'

import { workflowEditorVisitLogic } from './workflowEditorVisitLogic'
import { WorkflowLogicProps } from './workflowLogic'

export function WorkflowEditorVisitTracker(props: WorkflowLogicProps): null {
    useMountedLogic(workflowEditorVisitLogic(props))
    return null
}
