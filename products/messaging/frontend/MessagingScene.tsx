import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { actions, kea, listeners, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { router, urlToAction } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { CampaignsTable } from './Campaigns/CampaignsTable'
import type { messagingSceneLogicType } from './MessagingSceneType'
import { MessageSenders } from './Senders/MessageSenders'
import { MessageTemplatesTable } from './TemplateLibrary/MessageTemplatesTable'

const MESSAGING_SCENE_TABS = ['campaigns', 'library', 'senders'] as const
export type MessagingSceneTab = (typeof MESSAGING_SCENE_TABS)[number]

export type MessagingSceneProps = {
    tab: MessagingSceneTab
}

export const messagingSceneLogic = kea<messagingSceneLogicType>([
    props({} as MessagingSceneProps),
    path(() => ['scenes', 'messaging', 'messagingSceneLogic']),
    actions({
        setCurrentTab: (tab: MessagingSceneTab) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            'campaigns' as MessagingSceneTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    })),
    selectors({
        logicProps: [() => [(_, props) => props], (props) => props],
        breadcrumbs: [
            () => [(_, props) => props],
            ({ tab }): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Messaging,
                        name: 'Messaging',
                    },
                    {
                        key: [Scene.Messaging, tab],
                        name: capitalizeFirstLetter(tab.replaceAll('_', ' ')),
                    },
                ]
            },
        ],
    }),
    listeners({
        setCurrentTab: ({ tab }) => {
            router.actions.push(urls.messaging(tab))
        },
    }),
    urlToAction(({ actions, values }) => {
        return {
            // All possible routes for this scene need to be listed here
            [urls.messaging(':tab' as MessagingSceneTab)]: ({ tab }) => {
                let possibleTab: MessagingSceneTab = (tab as MessagingSceneTab) ?? 'campaigns'
                possibleTab = MESSAGING_SCENE_TABS.includes(possibleTab) ? possibleTab : 'campaigns'

                if (possibleTab !== values.currentTab) {
                    actions.setCurrentTab(possibleTab)
                }
            },
        }
    }),
])

export const scene: SceneExport = {
    component: MessagingScene,
    logic: messagingSceneLogic,
    paramsToProps: ({ params: { tab } }): (typeof messagingSceneLogic)['props'] => ({
        tab,
    }),
}

export function MessagingScene(): JSX.Element {
    const { currentTab } = useValues(messagingSceneLogic)
    const { setCurrentTab } = useActions(messagingSceneLogic)

    const hasMessagingFeatureFlag = useFeatureFlag('MESSAGING')

    if (!hasMessagingFeatureFlag) {
        return (
            <div className="flex flex-col justify-center items-center h-full">
                <h1 className="text-2xl font-bold">Coming soon!</h1>
                <p className="text-sm text-muted-foreground">
                    We're working on bringing messaging to PostHog. Stay tuned for updates!
                </p>
            </div>
        )
    }

    const tabs: LemonTab<MessagingSceneTab>[] = [
        {
            label: 'Campaigns',
            key: 'campaigns',
            content: (
                <>
                    <PageHeader
                        caption="Create automated messaging campaigns triggered by events"
                        buttons={
                            <LemonButton
                                data-attr="new-campaign"
                                to={urls.messagingCampaignNew()}
                                type="primary"
                                icon={<IconPlusSmall />}
                            >
                                New campaign
                            </LemonButton>
                        }
                    />
                    <CampaignsTable />
                </>
            ),
        },
        {
            label: 'Library',
            key: 'library',
            content: (
                <>
                    <PageHeader
                        caption="Create and manage messages"
                        buttons={
                            <LemonButton
                                data-attr="new-message-button"
                                icon={<IconPlusSmall />}
                                size="small"
                                type="primary"
                                to={urls.messagingLibraryTemplateNew()}
                            >
                                New template
                            </LemonButton>
                        }
                    />

                    <MessageTemplatesTable />
                </>
            ),
        },
        {
            label: 'Senders',
            key: 'senders',
            content: <MessageSenders />,
        },
    ]

    return <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} />
}
