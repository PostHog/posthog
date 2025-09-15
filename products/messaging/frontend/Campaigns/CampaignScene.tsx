import { useValues } from 'kea'
import { router } from 'kea-router'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { CampaignMetrics } from './CampaignMetrics'
import { CampaignOverview } from './CampaignOverview'
import { CampaignSceneHeader } from './CampaignSceneHeader'
import { CampaignWorkflow } from './CampaignWorkflow'
import { campaignLogic } from './campaignLogic'
import { CampaignSceneLogicProps, CampaignTab, campaignSceneLogic } from './campaignSceneLogic'
import { renderWorkflowLogMessage } from './logs/log-utils'

export const scene: SceneExport<CampaignSceneLogicProps> = {
    component: CampaignScene,
    logic: campaignSceneLogic,
    paramsToProps: ({ params: { id, tab } }) => ({ id: id || 'new', tab: tab || 'overview' }),
}

export function CampaignScene(props: CampaignSceneLogicProps): JSX.Element {
    const { currentTab } = useValues(campaignSceneLogic)

    const logic = campaignLogic(props)
    const { campaignLoading, campaign, originalCampaign } = useValues(logic)

    if (!originalCampaign && campaignLoading) {
        return <SpinnerOverlay sceneLevel />
    }

    if (!originalCampaign) {
        return <NotFound object="campaign" />
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
                  content: (
                      <LogsViewer
                          sourceType="hog_flow"
                          sourceId={props.id}
                          instanceLabel="workflow run"
                          renderMessage={(m) => renderWorkflowLogMessage(campaign, m)}
                      />
                  ),
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
        <SceneContent className="flex flex-col">
            <CampaignSceneHeader {...props} />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.messagingCampaign(props.id ?? 'new', tab))}
                tabs={tabs}
            />
        </SceneContent>
    )
}
