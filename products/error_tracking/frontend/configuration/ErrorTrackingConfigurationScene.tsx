import { actions, connect, kea, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router } from 'kea-router'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { Settings } from 'scenes/settings/Settings'
import { settingsLogic } from 'scenes/settings/settingsLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { ErrorTrackingSetupPrompt } from '../components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { ERROR_TRACKING_LOGIC_KEY } from '../utils'
import type { errorTrackingConfigurationSceneLogicType } from './ErrorTrackingConfigurationSceneType'

export type ConfigurationSceneTabType =
    | 'error-tracking-exception-autocapture'
    | 'error-tracking-user-groups'
    | 'error-tracking-symbol-sets'
    | 'error-tracking-custom-grouping'
    | 'error-tracking-alerting'

export interface ErrorTrackingConfigurationSceneLogicProps {
    initialTab?: ConfigurationSceneTabType
}

export const errorTrackingConfigurationSceneLogic = kea<errorTrackingConfigurationSceneLogicType>([
    path(['scenes', 'error-tracking', 'configuration', 'errorTrackingConfigurationSceneLogic']),
    props({} as ErrorTrackingConfigurationSceneLogicProps),

    connect(({ initialTab }: ErrorTrackingConfigurationSceneLogicProps) => ({
        actions: [
            settingsLogic({
                logicKey: ERROR_TRACKING_LOGIC_KEY,
                sectionId: 'environment-error-tracking',
                settingId: initialTab || 'error-tracking-exception-autocapture',
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
                    key: Scene.ErrorTracking,
                    path: urls.errorTracking(),
                    name: 'Error tracking',
                },
                {
                    key: Scene.ErrorTrackingConfiguration,
                    path: urls.errorTrackingConfiguration(),
                    name: 'Configuration',
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

export const scene: SceneExport = {
    component: ErrorTrackingConfigurationScene,
    logic: errorTrackingConfigurationSceneLogic,
    paramsToProps: ({ searchParams: { tab } }): (typeof errorTrackingConfigurationSceneLogic)['props'] => ({
        initialTab: tab,
    }),
}

export function ErrorTrackingConfigurationScene(): JSX.Element {
    return (
        <ErrorTrackingSetupPrompt>
            <Settings logicKey={ERROR_TRACKING_LOGIC_KEY} sectionId="environment-error-tracking" handleLocally />
        </ErrorTrackingSetupPrompt>
    )
}
