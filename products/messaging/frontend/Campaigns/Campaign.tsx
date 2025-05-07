import '@xyflow/react/dist/style.css'

import { useActions } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'

import { campaignLogic } from './campaignLogic'
import { WorkflowEditor } from './Workflows/WorkflowEditor'

// Wrapper component with ReactFlowProvider
export function Campaign(): JSX.Element {
    const { updateWorkflowJson } = useActions(campaignLogic)

    return (
        <div className="flex flex-col space-y-4">
            <div className="relative h-[calc(100vh-300px)] border rounded-md">
                <WorkflowEditor setFlowData={updateWorkflowJson} />
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: Campaign,
    logic: campaignLogic,
}
