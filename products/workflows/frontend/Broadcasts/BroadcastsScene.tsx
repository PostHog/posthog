import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { EmailSuspensionBanner } from '../EmailSuspensionBanner'
import { MessagingSetup } from '../MessagingSetup'
import { MessagingTabActions } from '../MessagingTabActions'
import {
    MESSAGING_NAV_TAB_KEYS,
    MESSAGING_TAB_CONTENT,
    MESSAGING_TAB_LABELS,
    MessagingNavTabKey,
    isMessagingSetupTab,
    messagingNavTabs,
} from '../messagingTabs'
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
    const { featureFlags } = useValues(featureFlagLogic)
    const newNavigationEnabled = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_NEW_NAVIGATION]

    const broadcastsTab = {
        label: 'Broadcasts',
        key: 'broadcasts' as const,
        link: urls.broadcasts(),
        content: (
            <>
                <BroadcastsFeaturePreview />
                <BroadcastsTable />
            </>
        ),
    }

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
            {newNavigationEnabled ? (
                <LemonTabs<'broadcasts' | 'library' | 'messaging-setup'>
                    activeKey={currentTab === 'broadcasts' || currentTab === 'library' ? currentTab : 'messaging-setup'}
                    tabs={[
                        broadcastsTab,
                        {
                            label: MESSAGING_TAB_LABELS.library,
                            key: 'library',
                            link: urls.broadcasts('library'),
                            content: MESSAGING_TAB_CONTENT.library,
                        },
                        {
                            label: 'Messaging setup',
                            key: 'messaging-setup',
                            link: urls.broadcasts('channels'),
                            content: (
                                <MessagingSetup
                                    tab={isMessagingSetupTab(currentTab) ? currentTab : 'channels'}
                                    linkFor={(tab) => urls.broadcasts(tab)}
                                />
                            ),
                        },
                    ]}
                    sceneInset
                />
            ) : (
                <LemonTabs
                    activeKey={currentTab}
                    tabs={[broadcastsTab, ...messagingNavTabs((tab) => urls.broadcasts(tab))]}
                    sceneInset
                />
            )}
        </SceneContent>
    )
}
