import { actions, kea, listeners, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { router, urlToAction } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Breadcrumb } from '~/types'

import { CampaignsTable } from './Campaigns/CampaignsTable'
import { MessageChannels } from './Channels/MessageChannels'
import type { messagingSceneLogicType } from './MessagingSceneType'
import { OptOutScene } from './OptOuts/OptOutScene'
import { MessageTemplatesTable } from './TemplateLibrary/MessageTemplatesTable'

const MESSAGING_SCENE_TABS = ['campaigns', 'library', 'channels', 'opt-outs'] as const
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
            (_, p) => [p.tab],
            (tab): Breadcrumb[] => {
                return [
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

export const scene: SceneExport<MessagingSceneProps> = {
    component: MessagingScene,
    logic: messagingSceneLogic,
    paramsToProps: ({ params: { tab } }) => ({ tab }),
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
                    <p>Create automated messaging campaigns triggered by events</p>
                    <CampaignsTable />
                </>
            ),
        },
        {
            label: 'Library',
            key: 'library',
            content: (
                <>
                    <p>Create and manage messages</p>
                    <MessageTemplatesTable />
                </>
            ),
        },
        {
            label: 'Channels',
            key: 'channels',
            content: <MessageChannels />,
        },
        {
            label: 'Opt-outs',
            key: 'opt-outs',
            content: <OptOutScene />,
        },
    ]

    return (
        <SceneContent className="messaging">
            <SceneTitleSection
                name="Messaging"
                resourceType={{ type: 'messaging' }}
                description="Create automated workflows triggered by PostHog events to onboard, retain, and re-engage your users."
                actions={
                    <>
                        {currentTab === 'campaigns' && (
                            <LemonButton
                                data-attr="new-campaign"
                                to={urls.messagingCampaignNew()}
                                type="primary"
                                size="small"
                            >
                                New campaign
                            </LemonButton>
                        )}
                        {currentTab === 'library' && (
                            <LemonButton
                                data-attr="new-message-button"
                                to={urls.messagingLibraryTemplateNew()}
                                type="primary"
                                size="small"
                            >
                                New template
                            </LemonButton>
                        )}
                    </>
                }
            />
            <SceneDivider />
            <LemonTabs activeKey={currentTab} tabs={tabs} onChange={setCurrentTab} sceneInset />
        </SceneContent>
    )
}
