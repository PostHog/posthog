import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { campaignLogic } from './campaignLogic'
import { CampaignMetrics } from './CampaignMetrics'
import { CampaignOverview } from './CampaignOverview'
import { campaignSceneLogic, CampaignSceneLogicProps, CampaignTab } from './campaignSceneLogic'
import { CampaignWorkflow } from './CampaignWorkflow'

export const scene: SceneExport = {
    component: CampaignScene,
    logic: campaignSceneLogic,
    paramsToProps: ({ params: { id, tab } }): CampaignSceneLogicProps => ({ id: id || 'new', tab: tab || 'overview' }),
}

export function CampaignScene(props: CampaignSceneLogicProps = {}): JSX.Element {
    const { currentTab } = useValues(campaignSceneLogic)

    const logic = campaignLogic(props)
    const { campaignChanged, isCampaignSubmitting } = useValues(logic)
    const { submitCampaign, discardChanges } = useActions(logic)

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
        props.id
            ? {
                  label: 'Logs',
                  key: 'logs',
                  content: <LogsViewer sourceType="hog_flow" sourceId={props.id} />,
              }
            : null,
        props.id
            ? {
                  label: 'Metrics',
                  key: 'metrics',
                  content: <CampaignMetrics id={props.id} />,
              }
            : null,
    ]

    return (
        <div className="flex flex-col space-y-4">
            <PageHeader
                buttons={
                    <>
                        {campaignChanged && (
                            <LemonButton
                                data-attr="discard-campaign-changes"
                                type="secondary"
                                onClick={() => discardChanges()}
                            >
                                Discard changes
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            form="campaign"
                            onClick={submitCampaign}
                            loading={isCampaignSubmitting}
                            disabledReason={campaignChanged ? undefined : 'No changes to save'}
                        >
                            {props.id === 'new' ? 'Create' : 'Save'}
                        </LemonButton>
                    </>
                }
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.messagingCampaign(props.id ?? 'new', tab))}
                tabs={tabs}
            />
        </div>
    )
}
