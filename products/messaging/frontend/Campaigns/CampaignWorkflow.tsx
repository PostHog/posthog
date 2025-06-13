import { useActions } from 'kea'

import { campaignLogic } from './campaignLogic'
import { WorkflowEditor } from './Workflows/WorkflowEditor'

export function CampaignWorkflow(): JSX.Element {
    const { updateCampaign } = useActions(campaignLogic)

    return (
        <div className="relative h-[calc(100vh-220px)] border rounded-md">
            <WorkflowEditor onChange={({ actions, edges }) => updateCampaign({ actions, edges })} />
        </div>
    )
}
