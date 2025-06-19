import { IconPlusSmall } from '@posthog/icons'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { CampaignsTable } from './CampaignsTable'

export function Campaigns(): JSX.Element {
    return (
        <>
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
        </>
    )
}
