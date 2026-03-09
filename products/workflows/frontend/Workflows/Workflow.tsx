import { useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { HogFlowEditor } from './hogflows/HogFlowEditor'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

export function Workflow(props: WorkflowLogicProps): JSX.Element {
    const { originalWorkflow, workflowLoading } = useValues(workflowLogic(props))

    return (
        <div className="flex flex-col grow relative border rounded-md">
            {!originalWorkflow && workflowLoading ? <SpinnerOverlay /> : <HogFlowEditor />}
        </div>
    )
}
