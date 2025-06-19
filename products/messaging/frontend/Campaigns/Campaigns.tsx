import { IconPlusSmall } from '@posthog/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { MessagingTabs } from '../MessagingTabs'
import { campaignsLogic } from './campaignsLogic'
import { CampaignsTable } from './CampaignsTable'

export function Campaigns(): JSX.Element {
    return (
        <div>
            <MessagingTabs key="campaigns-tabs" />
            <PageHeader
                caption="Create automated messaging campaigns triggered by events"
                buttons={
                    <LemonButton
                        data-attr="new-campaign"
                        to={urls.messagingCampaignNew()}
                        type="primary"
                        icon={<IconPlusSmall />}
                    >
                        New campaign
                    </LemonButton>
                }
            />
            <CampaignsTable />
        </div>
    )
}

export const scene: SceneExport = {
    component: Campaigns,
    logic: campaignsLogic,
}
