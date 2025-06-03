import '@xyflow/react/dist/style.css'

import { LemonTabs } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { capitalizeFirstLetter } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { campaignLogic, CampaignLogicProps, CampaignTab, CampaignTabs } from './campaignLogic'
import { WorkflowEditor } from './Workflows/WorkflowEditor'

export const scene: SceneExport = {
    component: Campaign,
    logic: campaignLogic,
    paramsToProps: ({ params: { id } }): CampaignLogicProps => ({
        id,
    }),
}

export function Campaign({ id }: CampaignLogicProps = {}): JSX.Element {
    const { currentTab } = useValues(campaignLogic)
    const { campaignLoading } = useValues(campaignLogic)

    const isNewCampaign = id === 'new'

    const tabContent = {
        overview: (
            <div className="flex flex-col gap-4">
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
            </div>
        ),
        workflow: (
            <div className="relative h-[calc(100vh-220px)] border rounded-md">
                <WorkflowEditor />
            </div>
        ),
    }

    const tabs = [
        {
            label: 'Workflow',
            key: 'workflow',
            content: tabContent.workflow,
        },
    ]

    if (!isNewCampaign) {
        tabs.unshift({
            label: 'Overview',
            key: 'overview',
            content: tabContent.overview,
        })
    }

    return (
        <div className="flex flex-col space-y-4">
            <PageHeader />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.messagingCampaignTab(id, tab as CampaignTab))}
                tabs={CampaignTabs.map((tab) => ({
                    label: capitalizeFirstLetter(tab),
                    key: tab,
                    content: tabContent[tab],
                }))}
            />
        </div>
    )
}
