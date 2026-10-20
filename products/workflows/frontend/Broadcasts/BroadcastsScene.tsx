import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
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
    MessagingNavTabKey,
    isMessagingSetupTab,
} from '../messagingTabs'
import { SendCalendar } from '../SendCalendar/SendCalendar'
import { SendCalendarTabLabel } from '../SendCalendar/SendCalendarTabLabel'
import { NewWorkflowModal } from '../Workflows/NewWorkflowModal'
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
    const showCalendar = useFeatureFlag('WORKFLOWS_SEND_CALENDAR')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const lastSegment = location.pathname.split('/').pop() as MessagingNavTabKey | 'calendar'
    const currentTab: MessagingNavTabKey | 'broadcasts' | 'calendar' =
        lastSegment === 'calendar'
            ? showCalendar
                ? 'calendar'
                : 'broadcasts'
            : MESSAGING_NAV_TAB_KEYS.includes(lastSegment)
              ? lastSegment
              : 'broadcasts'

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
                    currentTab === 'broadcasts' || currentTab === 'calendar' ? (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Workflow}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            {todayRailNav ? (
                                <Button data-attr="new-broadcast" onClick={startNewBroadcast} variant="primary">
                                    New broadcast
                                </Button>
                            ) : (
                                <LemonButton
                                    data-attr="new-broadcast"
                                    onClick={startNewBroadcast}
                                    type="primary"
                                    size="small"
                                >
                                    New broadcast
                                </LemonButton>
                            )}
                        </AccessControlAction>
                    ) : (
                        <MessagingTabActions tab={currentTab} channelsUrl={urls.broadcasts('channels')} />
                    )
                }
            />
            <EmailSuspensionBanner />
            <LemonTabs<'broadcasts' | 'calendar' | 'library' | 'messaging-setup'>
                activeKey={
                    currentTab === 'broadcasts' || currentTab === 'calendar' || currentTab === 'library'
                        ? currentTab
                        : 'messaging-setup'
                }
                tabs={[
                    broadcastsTab,
                    showCalendar
                        ? {
                              label: <SendCalendarTabLabel />,
                              key: 'calendar',
                              link: urls.broadcasts('calendar'),
                              content: <SendCalendar />,
                          }
                        : null,
                    {
                        label: 'Templates',
                        key: 'library',
                        link: urls.broadcasts('library'),
                        content: MESSAGING_TAB_CONTENT.library,
                    },
                    {
                        label: 'Messaging',
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
            {/* The calendar can start a workflow, and its template picker lives in this modal. */}
            {showCalendar ? <NewWorkflowModal /> : null}
        </SceneContent>
    )
}
