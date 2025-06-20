import { SpinnerOverlay } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'

import { campaignLogic, CampaignLogicProps } from './campaignLogic'
import { HogFlowEditor } from './hogflows/HogFlowEditor'

export function CampaignWorkflow(props: CampaignLogicProps): JSX.Element {
    const logic = useMountedLogic(campaignLogic(props))
    const { campaign, campaignLoading } = useValues(logic)
    const { setCampaignValues } = useActions(logic)

    return (
        <div className="relative h-[calc(100vh-220px)] border rounded-md">
            {campaignLoading ? (
                <SpinnerOverlay />
            ) : (
                <HogFlowEditor hogFlow={campaign} onChange={({ actions }) => setCampaignValues({ actions })} />
            )}
        </div>
    )
}
