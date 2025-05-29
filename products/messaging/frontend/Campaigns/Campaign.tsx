import '@xyflow/react/dist/style.css'

import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { CAMPAIGN_TAB_TO_NAME, campaignLogic, CampaignLogicProps, CampaignTabs } from './campaignLogic'
import { WorkflowEditor } from './Workflows/WorkflowEditor'

export const scene: SceneExport = {
    component: Campaign,
    logic: campaignLogic,
    paramsToProps: ({ params: { id } }): CampaignLogicProps => ({
        id,
    }),
}

// Wrapper component with ReactFlowProvider
export function Campaign({ id }: CampaignLogicProps = {}): JSX.Element {
    const { currentTab } = useValues(campaignLogic)
    const { updateWorkflow } = useActions(campaignLogic)
    const { campaign, campaignLoading, campaignChanged, isCampaignPublishing } = useValues(campaignLogic)

    const isNewCampaign = id === 'new'

    const tabContent = {
        [CampaignTabs.Overview]: (
            <Form logic={campaignLogic} formKey="campaign">
                <div className="flex flex-wrap gap-4 items-start">
                    <div className="flex-1 self-start p-3 space-y-2 rounded border min-w-100 bg-surface-primary">
                        <LemonField name="name" label="Name">
                            <LemonInput disabled={campaignLoading} />
                        </LemonField>

                        <LemonField
                            name="description"
                            label="Description"
                            info="Add a description to share context with other team members"
                        >
                            <LemonInput disabled={campaignLoading} />
                        </LemonField>
                    </div>
                </div>
            </Form>
        ),
        [CampaignTabs.Workflow]: (
            <div className="relative h-[calc(100vh-220px)] border rounded-md">
                <WorkflowEditor setWorkflow={updateWorkflow} />
            </div>
        ),
    }

    const tabs = [
        {
            label: 'Workflow',
            key: CampaignTabs.Workflow,
            content: tabContent[CampaignTabs.Workflow],
        },
    ]

    if (!isNewCampaign) {
        tabs.unshift({
            label: 'Overview',
            key: CampaignTabs.Overview,
            content: tabContent[CampaignTabs.Overview],
        })
    }

    return (
        <div className="flex flex-col space-y-4">
            <PageHeader
                buttons={
                    <>
                        {campaignChanged && (
                            <LemonButton data-attr="cancel-message-template" type="secondary">
                                Discard changes
                            </LemonButton>
                        )}
                        <LemonButton
                            type="primary"
                            htmlType="submit"
                            form="template"
                            loading={isCampaignPublishing}
                            disabledReason={campaignChanged ? undefined : 'No changes to save'}
                        >
                            {isNewCampaign ? 'Create' : 'Save'}
                        </LemonButton>
                    </>
                }
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.messagingCampaignTab(id, tab as CampaignTabs))}
                tabs={Object.values(CampaignTabs).map((tab) => ({
                    label: CAMPAIGN_TAB_TO_NAME[tab],
                    key: tab,
                    content: tabContent[tab],
                }))}
            />
        </div>
    )
}
