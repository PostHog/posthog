import { BindLogic, useValues } from 'kea'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { CampaignLogicProps, campaignLogic } from './campaignLogic'
import { HogFlowEditor } from './hogflows/HogFlowEditor'

export function CampaignWorkflow(props: CampaignLogicProps): JSX.Element {
    const { originalCampaign, campaignLoading } = useValues(campaignLogic(props))

    return (
        <div className="relative border rounded-md h-[calc(100vh-280px)]">
            <BindLogic logic={campaignLogic} props={props}>
                {!originalCampaign && campaignLoading ? <SpinnerOverlay /> : <HogFlowEditor />}
            </BindLogic>
        </div>
    )
}
