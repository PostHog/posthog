import { useMountedLogic } from 'kea'

import { workflowEditorVisitLogic } from './workflowEditorVisitLogic'
import { WorkflowLogicProps } from './workflowLogic'

/** Rendered only where the builder shows, so notebook embeds and the AI composer stay out of the funnel. */
export function WorkflowEditorVisitTracker(props: WorkflowLogicProps): null {
    useMountedLogic(workflowEditorVisitLogic(props))
    return null
}
