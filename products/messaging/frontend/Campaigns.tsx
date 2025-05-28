import { IconPlusSmall } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { HogFunctionConfiguration } from 'scenes/hog-functions/configuration/HogFunctionConfiguration'
import { HogFunctionLogs } from 'scenes/hog-functions/logs/HogFunctionLogs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { campaignsLogic } from './campaignsLogic'
import { CampaignTab, campaignTabsLogic } from './campaignTabsLogic'
import { FunctionsTable } from './FunctionsTable'
import { MessagingTabs } from './MessagingTabs'

const Campaign = ({ campaignId }: { campaignId: string }): JSX.Element => {
    const { currentTab } = useValues(campaignTabsLogic)
    const { setTab } = useActions(campaignTabsLogic)

    const tabs = [
        { key: 'configuration', label: 'Configuration' },
        { key: 'logs', label: 'Logs' },
    ]

    return (
        <div className="flex flex-col">
            {campaignId !== 'new' && (
                <LemonTabs activeKey={currentTab} onChange={(tab) => setTab(tab as CampaignTab)} tabs={tabs} />
            )}

            {currentTab === 'configuration' && (
                <HogFunctionConfiguration
                    id={campaignId === 'new' ? null : campaignId}
                    templateId={campaignId === 'new' ? 'template-new-campaign' : ''}
                    displayOptions={{
                        showPersonsCount: false,
                        showExpectedVolume: true,
                        canEditSource: false,
                    }}
                />
            )}
            {currentTab === 'logs' && <HogFunctionLogs hogFunctionId={campaignId} />}
        </div>
    )
}

export function Campaigns(): JSX.Element {
    const { campaignId } = useValues(campaignsLogic)
    return campaignId ? (
        <Campaign campaignId={campaignId} />
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
