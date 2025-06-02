import { IconPlusSmall } from '@posthog/icons'
import { useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { FunctionsTable } from '../FunctionsTable'
import { MessagingTabs } from '../MessagingTabs'
import { Campaign } from './Campaign'
import { campaignsLogic } from './campaignsLogic'

export function Campaigns(): JSX.Element {
    const { campaignId } = useValues(campaignsLogic)
    return campaignId ? (
        <Campaign id={campaignId} />
    ) : (
        <>
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
            <FunctionsTable type="destination" kind="messaging_campaign" />
        </>
    )
}

export const scene: SceneExport = {
    component: Campaigns,
    logic: campaignsLogic,
}
