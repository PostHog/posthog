import { actions, kea, path, props, reducers, selectors, useActions, useValues } from 'kea'
import { urlToAction } from 'kea-router'

import { IconLetter, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { Breadcrumb } from '~/types'

import { MessageChannels } from './Channels/MessageChannels'
import { OptOutScene } from './OptOuts/OptOutScene'
import { optOutCategoriesLogic } from './OptOuts/optOutCategoriesLogic'
import { MessageTemplatesTable } from './TemplateLibrary/MessageTemplatesTable'
import { WorkflowsTable } from './Workflows/WorkflowsTable'
import type { workflowSceneLogicType } from './WorkflowsSceneType'

const WORKFLOW_SCENE_TABS = ['workflows', 'library', 'channels', 'opt-outs'] as const
export type WorkflowsSceneTab = (typeof WORKFLOW_SCENE_TABS)[number]

export type WorkflowsSceneProps = {
    tab: WorkflowsSceneTab
}

export const workflowSceneLogic = kea<workflowSceneLogicType>([
    props({} as WorkflowsSceneProps),
    path(() => ['scenes', 'workflows', 'workflowSceneLogic']),
    actions({
        setCurrentTab: (tab: WorkflowsSceneTab) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            'workflows' as WorkflowsSceneTab,
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
                        key: [Scene.Workflows, tab],
                        name: capitalizeFirstLetter(tab.replaceAll('_', ' ')),
                        iconType: 'workflows',
                    },
                ]
            },
        ],
    }),
    urlToAction(({ actions, values }) => {
        return {
            [urls.workflows()]: () => {
                if (values.currentTab !== 'workflows') {
                    actions.setCurrentTab('workflows')
                }
            },
            [urls.workflows(':tab' as WorkflowsSceneTab)]: ({ tab }) => {
                let possibleTab: WorkflowsSceneTab = (tab as WorkflowsSceneTab) ?? 'workflows'
                possibleTab = WORKFLOW_SCENE_TABS.includes(possibleTab) ? possibleTab : 'workflows'

                if (possibleTab !== values.currentTab) {
                    actions.setCurrentTab(possibleTab)
                }
            },
        }
    }),
])

export const scene: SceneExport<WorkflowsSceneProps> = {
    component: WorkflowsScene,
    logic: workflowSceneLogic,
    paramsToProps: ({ params: { tab } }) => ({ tab }),
}

export function WorkflowsScene(): JSX.Element {
    const { currentTab } = useValues(workflowSceneLogic)
    const { openSetupModal } = useActions(integrationsLogic)
    const { openNewCategoryModal } = useActions(optOutCategoriesLogic)

    const hasWorkflowsFeatureFlag = useFeatureFlag('WORKFLOWS')

    if (!hasWorkflowsFeatureFlag) {
        return (
            <div className="flex flex-col justify-center items-center h-full">
                <h1 className="text-2xl font-bold">Coming soon!</h1>
                <p className="text-sm text-muted-foreground">
                    We're working on bringing workflows to PostHog. Stay tuned for updates!
                </p>
            </div>
        )
    }

    const newChannelMenuItems: LemonMenuItems = [
        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconLetter /> Email
                </div>
            ),
            onClick: () => openSetupModal(undefined, 'email'),
        },

        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconSlack /> Slack
                </div>
            ),
            disableClientSideRouting: true,
            to: api.integrations.authorizeUrl({
                kind: 'slack',
                next: urls.workflows('channels'),
            }),
        },
        {
            label: (
                <div className="flex gap-1 items-center">
                    <IconTwilio /> Twilio
                </div>
            ),
            onClick: () => openSetupModal(undefined, 'twilio'),
        },
    ]

    const tabs: LemonTab<WorkflowsSceneTab>[] = [
        {
            label: 'Workflows',
            key: 'workflows',
            content: (
                <>
                    <p>Create automated workflows workflows triggered by events</p>
                    <WorkflowsTable />
                </>
            ),
            link: urls.workflows(),
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
            link: urls.workflows('library'),
        },
        {
            label: 'Channels',
            key: 'channels',
            content: <MessageChannels />,
            link: urls.workflows('channels'),
        },
        {
            label: 'Opt-outs',
            key: 'opt-outs',
            content: <OptOutScene />,
            link: urls.workflows('opt-outs'),
        },
    ]

    return (
        <SceneContent className="workflows">
            <SceneTitleSection
                name={sceneConfigurations[Scene.Workflows].name}
                description={sceneConfigurations[Scene.Workflows].description}
                resourceType={{ type: sceneConfigurations[Scene.Workflows].iconType || 'default_icon_type' }}
                actions={
                    <>
                        {currentTab === 'workflows' && (
                            <LemonButton data-attr="new-workflow" to={urls.workflowNew()} type="primary" size="small">
                                New workflow
                            </LemonButton>
                        )}
                        {currentTab === 'library' && (
                            <LemonButton
                                data-attr="new-message-button"
                                to={urls.workflowsLibraryTemplateNew()}
                                type="primary"
                                size="small"
                            >
                                New template
                            </LemonButton>
                        )}
                        {currentTab === 'channels' && (
                            <LemonMenu items={newChannelMenuItems} matchWidth>
                                <LemonButton
                                    data-attr="new-channel-button"
                                    icon={<IconPlusSmall />}
                                    size="small"
                                    type="primary"
                                >
                                    New channel
                                </LemonButton>
                            </LemonMenu>
                        )}
                        {currentTab === 'opt-outs' && (
                            <LemonButton
                                data-attr="new-optout-category"
                                icon={<IconPlusSmall />}
                                size="small"
                                type="primary"
                                onClick={() => openNewCategoryModal()}
                            >
                                New category
                            </LemonButton>
                        )}
                    </>
                }
            />
            <SceneDivider />
            <LemonTabs activeKey={currentTab} tabs={tabs} sceneInset />
        </SceneContent>
    )
}
