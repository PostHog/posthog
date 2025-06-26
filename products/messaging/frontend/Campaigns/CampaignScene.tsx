import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { campaignLogic } from './campaignLogic'
import { CampaignMetrics } from './CampaignMetrics'
import { CampaignOverview } from './CampaignOverview'
import { campaignSceneLogic, CampaignSceneLogicProps, CampaignTab } from './campaignSceneLogic'
import { CampaignWorkflow } from './CampaignWorkflow'
import { SpinnerOverlay } from '@posthog/lemon-ui'
import { CampaignSceneHeader } from './CampaignSceneHeader'

export const scene: SceneExport = {
    component: CampaignScene,
    logic: campaignSceneLogic,
    paramsToProps: ({ params: { id, tab } }): CampaignSceneLogicProps => ({ id: id || 'new', tab: tab || 'overview' }),
}

export function CampaignScene(props: CampaignSceneLogicProps = {}): JSX.Element {
    const { currentTab } = useValues(campaignSceneLogic)

    const logic = campaignLogic(props)
    const { campaignLoading } = useValues(logic)

    if (campaignLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    const tabs: (LemonTab<CampaignTab> | null)[] = [
        {
            label: 'Overview',
            key: 'overview',
            content: <CampaignOverview {...props} />,
        },
        {
            label: 'Workflow',
            key: 'workflow',
            content: <CampaignWorkflow {...props} />,
        },
        props.id && props.id !== 'new'
            ? {
                  label: 'Logs',
                  key: 'logs',
                  content: <LogsViewer sourceType="hog_flow" sourceId={props.id} />,
              }
            : null,
        props.id && props.id !== 'new'
            ? {
                  label: 'Metrics',
                  key: 'metrics',
                  content: <CampaignMetrics id={props.id} />,
              }
            : null,
    ]

    return (
        <div className="flex flex-col space-y-4">
            <CampaignSceneHeader {...props} />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.messagingCampaign(props.id ?? 'new', tab))}
                tabs={tabs}
            />
        </div>
    )
}
