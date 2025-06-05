import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { CampaignTab } from './campaignLogic'
import { CampaignOverview } from './CampaignOverview'
import { campaignSceneLogic, CampaignSceneLogicProps } from './campaignSceneLogic'
import { CampaignWorkflow } from './CampaignWorkflow'

export const scene: SceneExport = {
    component: CampaignScene,
    logic: campaignSceneLogic,
    paramsToProps: ({ params: { id } }): CampaignSceneLogicProps => ({ id: id || 'new' }),
}

export function CampaignScene({ id }: { id?: string } = {}): JSX.Element {
    const { currentTab } = useValues(campaignSceneLogic)

    const isNewCampaign = id === 'new'

    const tabs = [
        {
            label: 'Workflow',
            key: 'workflow',
            content: <CampaignWorkflow />,
        },
    ]

    if (!isNewCampaign) {
        tabs.unshift({
            label: 'Overview',
            key: 'overview',
            content: <CampaignOverview />,
        })
    }

    return (
        <div className="flex flex-col space-y-4">
            <PageHeader />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.messagingCampaignTab(id, tab as CampaignTab))}
                tabs={tabs}
            />
        </div>
    )
}
