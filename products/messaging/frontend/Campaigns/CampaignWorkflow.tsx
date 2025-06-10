import '@xyflow/react/dist/style.css'

import { WorkflowEditor } from './Workflows/WorkflowEditor'

export function CampaignWorkflow(): JSX.Element {
    return (
        <div className="relative h-[calc(100vh-220px)] border rounded-md">
            <WorkflowEditor />
        </div>
    )
}
