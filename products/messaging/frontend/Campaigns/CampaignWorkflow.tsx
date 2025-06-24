import { SpinnerOverlay } from '@posthog/lemon-ui'
import { BindLogic, useValues } from 'kea'

import { campaignLogic, CampaignLogicProps } from './campaignLogic'
import { HogFlowEditor } from './hogflows/HogFlowEditor'

export function CampaignWorkflow(props: CampaignLogicProps): JSX.Element {
    const { campaignLoading, campaign } = useValues(campaignLogic(props))

    return (
        <div className="relative h-[calc(100vh-220px)] border rounded-md">
            <BindLogic logic={campaignLogic} props={props}>
                {!campaign && campaignLoading ? <SpinnerOverlay /> : <HogFlowEditor />}
            </BindLogic>
        </div>
    )
}
