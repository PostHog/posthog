import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { HogFlowEditor } from './hogflows/HogFlowEditor'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

export function Workflow(props: WorkflowLogicProps): JSX.Element {
    const { originalWorkflow, workflowLoading } = useValues(workflowLogic(props))

    return (
        <div className="flex flex-col grow relative border rounded-md">
            <BindLogic logic={workflowLogic} props={props}>
                {!originalWorkflow && workflowLoading ? <SpinnerOverlay /> : <HogFlowEditor />}
            </BindLogic>
        </div>
    )
}
