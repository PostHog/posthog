import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

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
import { MESSAGING_NAV_TAB_KEYS, MessagingNavTabKey, messagingNavTabs } from '../messagingTabs'
import { SendingLimitsBanner } from '../SendingLimitsBanner'
import { BroadcastsFeaturePreview } from './BroadcastsFeaturePreview'
import { BroadcastsTable } from './BroadcastsTable'
import { newBroadcastAgentLogic } from './newBroadcastAgentLogic'

export const scene: SceneExport = {
    component: BroadcastsScene,
    productKey: ProductKey.WORKFLOWS,
}

export function BroadcastsScene(): JSX.Element {
    const { location } = useValues(router)
    const { startNewBroadcast } = useActions(newBroadcastAgentLogic)
    // The tab routes are literal paths, so the tab is the last path segment rather than a route param.
    const lastSegment = location.pathname.split('/').pop() as MessagingNavTabKey
    const currentTab: MessagingNavTabKey | 'broadcasts' = MESSAGING_NAV_TAB_KEYS.includes(lastSegment)
        ? lastSegment
        : 'broadcasts'

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
            <SendingLimitsBanner
                sendingAllowanceUrl={currentTab === 'reputation' ? undefined : urls.broadcasts('reputation')}
            />
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
