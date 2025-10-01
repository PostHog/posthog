import { actions, connect, kea, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router } from 'kea-router'

import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'
import { settingsLogic } from 'scenes/settings/settingsLogic'
import { urls } from 'scenes/urls'

import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { Breadcrumb } from '~/types'

import { FEEDBACK_LOGIC_KEY } from '../../utils'
import type { feedbackConfigurationSceneLogicType } from './FeedbackConfigurationSceneType'

export type ConfigurationSceneTabType = 'feedback-general'

export interface FeedbackConfigurationSceneLogicProps {
    initialTab?: ConfigurationSceneTabType
}

export const feedbackConfigurationSceneLogic = kea<feedbackConfigurationSceneLogicType>([
    path(['scenes', 'feedback', 'configuration', 'feedbackConfigurationSceneLogic']),
    props({} as FeedbackConfigurationSceneLogicProps),

    connect(({ initialTab }: FeedbackConfigurationSceneLogicProps) => ({
        actions: [
            settingsLogic({
                logicKey: FEEDBACK_LOGIC_KEY,
                sectionId: 'environment-feedback',
                settingId: initialTab || 'feedback-general',
            }),
            ['selectSetting'],
        ],
    })),

    actions({
        setTab: (tab: ConfigurationSceneTabType) => ({ tab }),
    }),

    reducers(({ props }) => ({
        tab: [
            props.initialTab as ConfigurationSceneTabType,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.FeedbackList,
                    path: urls.feedbackList(),
                    name: 'Feedback',
                    iconType: 'comment',
                },
                {
                    key: Scene.FeedbackConfiguration,
                    path: urls.feedbackConfiguration(),
                    name: 'Configuration',
                    iconType: 'comment',
                },
            ],
        ],
    }),

    actionToUrl({
        selectSetting: ({ setting }) => {
            const { currentLocation } = router.values

            return [
                currentLocation.pathname,
                { ...currentLocation.searchParams, tab: setting },
                currentLocation.hashParams,
            ]
        },
    }),
])

export const scene: SceneExport<FeedbackConfigurationSceneLogicProps> = {
    component: FeedbackConfigurationScene,
    logic: feedbackConfigurationSceneLogic,
    paramsToProps: ({ searchParams: { tab } }) => ({ initialTab: tab }),
}

export function FeedbackConfigurationScene(): JSX.Element {
    return (
        <>
            <div className="mb-2 -ml-[var(--button-padding-x-lg)]">
                <SceneBreadcrumbBackButton />
            </div>
            <Settings logicKey={FEEDBACK_LOGIC_KEY} sectionId="environment-feedback" handleLocally />
        </>
    )
}
