import { useValues } from 'kea'
import { router } from 'kea-router'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'

import { CampaignMetrics } from './CampaignMetrics'
import { CampaignSceneHeader } from './CampaignSceneHeader'
import { CampaignWorkflow } from './CampaignWorkflow'
import { campaignLogic } from './campaignLogic'
import { CampaignSceneLogicProps, CampaignTab, campaignSceneLogic } from './campaignSceneLogic'
import { renderWorkflowLogMessage } from './logs/log-utils'

export const scene: SceneExport<CampaignSceneLogicProps> = {
    component: CampaignScene,
    logic: campaignSceneLogic,
    paramsToProps: ({ params: { id, tab } }) => ({ id: id || 'new', tab: tab || 'workflow' }),
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
            label: 'Workflow',
            key: 'workflow',
            content: <CampaignWorkflow {...props} />,
        },

        {
            label: 'Logs',
            key: 'logs',
            content: (
                <LogsViewer
                    sourceType="hog_flow"
                    /**
                     * If we're rendering tabs, props.id is guaranteed to be
                     * defined and not "new" (see return statement below)
                     */
                    sourceId={props.id!}
                    instanceLabel="workflow run"
                    renderMessage={(m) => renderWorkflowLogMessage(campaign, m)}
                />
            ),
        },
        {
            label: 'Metrics',
            key: 'metrics',
            /**
             * If we're rendering tabs, props.id is guaranteed to be
             * defined and not "new" (see return statement below)
             */
            content: <CampaignMetrics id={props.id!} />,
        },
    ]

    return (
        <SceneContent className="flex flex-col">
            <CampaignSceneHeader {...props} />
            <SceneDivider />
            {/* Only show Logs and Metrics tabs if the campaign has already been created */}
            {!props.id || props.id === 'new' ? (
                <CampaignWorkflow {...props} />
            ) : (
                <LemonTabs
                    activeKey={currentTab}
                    onChange={(tab) => router.actions.push(urls.messagingCampaign(props.id ?? 'new', tab))}
                    tabs={tabs}
                    sceneInset
                />
            )}
        </SceneContent>
    )
}
