import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { campaignLogic } from './campaignLogic'
import { CampaignOverview } from './CampaignOverview'
import { campaignSceneLogic, CampaignSceneLogicProps } from './campaignSceneLogic'
import { CampaignWorkflow } from './CampaignWorkflow'

export const scene: SceneExport = {
    component: CampaignScene,
    logic: campaignSceneLogic,
    paramsToProps: ({ params: { id, tab } }): CampaignSceneLogicProps => ({ id: id || 'new', tab: tab || 'overview' }),
}

export function CampaignScene(props: CampaignSceneLogicProps = {}): JSX.Element {
    const { currentTab } = useValues(campaignSceneLogic)

    const logic = campaignLogic(props)
    const { campaignChanged, originalCampaign, isCampaignSubmitting } = useValues(logic)
    const { submitCampaign, resetCampaign } = useActions(logic)

    const tabs = [
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
                                onClick={() => resetCampaign(originalCampaign)}
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
