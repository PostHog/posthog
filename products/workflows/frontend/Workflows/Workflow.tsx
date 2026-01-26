import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { HogFlowEditor } from './hogflows/HogFlowEditor'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

export function Workflow(props: WorkflowLogicProps): JSX.Element {
    return (
        <BindLogic logic={workflowLogic} props={props}>
            <WorkflowContent />
        </BindLogic>
    )
}

function WorkflowContent(): JSX.Element {
    const { originalWorkflow, workflowLoading } = useValues(workflowLogic)

    if (!originalWorkflow && workflowLoading) {
        return <SpinnerOverlay />
    }

    if (!originalWorkflow) {
        return <div>Workflow not found</div>
    }

    return <HogFlowEditor />
}
