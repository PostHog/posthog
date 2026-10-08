import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EmailSuspensionBanner } from '../EmailSuspensionBanner'
import { MessagingTabActions } from '../MessagingTabActions'
import { messagingNavTabs } from '../messagingTabs'
import { BroadcastsFeaturePreview } from './BroadcastsFeaturePreview'
import { broadcastsSceneLogic } from './broadcastsSceneLogic'
import { BroadcastsTable } from './BroadcastsTable'
import { newBroadcastAgentLogic } from './newBroadcastAgentLogic'

export const scene: SceneExport = {
    component: BroadcastsScene,
    logic: broadcastsSceneLogic,
    productKey: ProductKey.WORKFLOWS,
}

export function BroadcastsScene(): JSX.Element {
    const { currentTab } = useValues(broadcastsSceneLogic)
    const { startNewBroadcast } = useActions(newBroadcastAgentLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Broadcasts"
                description="Send a one-time or scheduled email to a group of people"
                resourceType={{ type: 'broadcasts' }}
                actions={
                    currentTab === 'broadcasts' ? (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                data-attr="new-broadcast"
                                onClick={startNewBroadcast}
                                type="primary"
                                size="small"
                            >
                                New broadcast
                            </LemonButton>
                        </AccessControlAction>
                    ) : (
                        <MessagingTabActions tab={currentTab} channelsUrl={urls.broadcasts('channels')} />
                    )
                }
            />
            <EmailSuspensionBanner />
            <LemonTabs
                activeKey={currentTab}
                tabs={[
                    {
                        label: 'Broadcasts',
                        key: 'broadcasts',
                        link: urls.broadcasts(),
                        content: (
                            <>
                                <BroadcastsFeaturePreview />
                                <BroadcastsTable />
                            </>
                        ),
                    },
                    ...messagingNavTabs((tab) => urls.broadcasts(tab)),
                ]}
                sceneInset
            />
        </SceneContent>
    )
}
