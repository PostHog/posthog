import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { useEffect, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

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
    const [isStopModalOpen, setIsStopModalOpen] = useState(false)
    const [stopType, setStopType] = useState<'trigger' | 'all'>('trigger')
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)

    const logic = campaignLogic(props)
    const { campaignChanged, originalCampaign, isCampaignSubmitting, campaign } = useValues(logic)
    const { submitCampaign, resetCampaign, saveCampaign } = useActions(logic)

    useEffect(() => {
        if (!currentTeam?.live_events_token) {
            return
        }

        const url = new URL(`${liveEventsHostOrigin()}/events`)
        url.searchParams.append('eventType', 'campaign_view')
        url.searchParams.append('distinctId', user?.email || '')
        url.searchParams.append('token', currentTeam.live_events_token)

        const eventSource = new EventSource(url.toString())

        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data)
            if (data.event === 'campaign_view' && data.properties?.campaign_id === props.id) {
                // We're not displaying viewers anymore, so we can ignore this
            }
        }

        // Send initial view event
        void fetch(`${liveEventsHostOrigin()}/stats`, {
            headers: {
                Authorization: `Bearer ${currentTeam.live_events_token}`,
            },
            method: 'POST',
            body: JSON.stringify({
                event: 'campaign_view',
                properties: {
                    campaign_id: props.id,
                    user_email: user?.email,
                },
            }),
        })

        return () => {
            eventSource.close()
        }
    }, [props.id, currentTeam?.live_events_token, user?.email])

    useEffect(() => {
        if (campaign.id && campaign.id !== 'new') {
            void logic.actions.loadCampaign()
        }
    }, [campaign.id, logic.actions])

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
                caption={
                    <div className="flex items-center gap-2">
                        <span>{campaign.name || 'Untitled Campaign'}</span>
                        {campaign.status === 'draft' && <span>(Draft)</span>}
                    </div>
                }
                buttons={
                    <>
                        {campaign?.status === 'active' && (
                            <>
                                <LemonButton
                                    data-attr="pause-campaign"
                                    type="secondary"
                                    onClick={() => saveCampaign({ ...campaign, status: 'draft' })}
                                >
                                    Pause
                                </LemonButton>
                                <LemonButton
                                    data-attr="stop-campaign"
                                    type="secondary"
                                    status="danger"
                                    onClick={() => setIsStopModalOpen(true)}
                                >
                                    Stop
                                </LemonButton>
                            </>
                        )}
                        {campaign?.status === 'draft' && (
                            <LemonButton
                                data-attr="resume-campaign"
                                type="secondary"
                                onClick={() => saveCampaign({ ...campaign, status: 'active' })}
                            >
                                Resume
                            </LemonButton>
                        )}
                        {campaignChanged && (
                            <LemonButton
                                data-attr="cancel-message-template"
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
                onChange={(tab) => router.actions.push(urls.messagingCampaignTab(props.id, tab))}
                tabs={tabs}
            />

            <LemonModal
                isOpen={isStopModalOpen}
                onClose={() => setIsStopModalOpen(false)}
                title="Stop Campaign"
                description="How would you like to stop this campaign?"
                footer={
                    <div className="flex justify-end gap-2">
                        <LemonButton type="secondary" onClick={() => setIsStopModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            status="danger"
                            onClick={() => {
                                saveCampaign({ ...campaign, status: 'archived', stop_type: stopType })
                                setIsStopModalOpen(false)
                            }}
                        >
                            Stop Campaign
                        </LemonButton>
                    </div>
                }
            >
                <div className="space-y-4">
                    <LemonRadio
                        value={stopType}
                        onChange={setStopType}
                        options={[
                            {
                                value: 'trigger',
                                label: 'Stop new events from triggering',
                                description:
                                    'New events will not trigger the campaign or any workflow steps, but existing customers will continue through the workflow',
                            },
                            {
                                value: 'all',
                                label: 'Stop all customer movement',
                                description:
                                    'No new events will trigger the campaign and all customers will stop moving through the workflow',
                            },
                        ]}
                    />
                </div>
            </LemonModal>
        </div>
    )
}
