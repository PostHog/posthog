import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { CampaignOverview } from './CampaignOverview'
import { campaignSceneLogic, CampaignSceneLogicProps } from './campaignSceneLogic'
import { CampaignWorkflow } from './CampaignWorkflow'

export const scene: SceneExport = {
    component: CampaignScene,
    logic: campaignSceneLogic,
    paramsToProps: ({ params: { id, tab } }): CampaignSceneLogicProps => ({ id: id || 'new', tab: tab || 'overview' }),
}

export function CampaignScene({ id }: { id?: string } = {}): JSX.Element {
    const { currentTab } = useValues(campaignSceneLogic)

    const tabs = [
        {
            label: 'Overview',
            key: 'overview',
            content: <CampaignOverview />,
        },
        {
            label: 'Workflow',
            key: 'workflow',
            content: <CampaignWorkflow />,
        },
    ]

    return (
        <div className="flex flex-col space-y-4">
            <PageHeader />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.messagingCampaignTab(id, tab))}
                tabs={tabs}
            />
        </div>
    )
}
