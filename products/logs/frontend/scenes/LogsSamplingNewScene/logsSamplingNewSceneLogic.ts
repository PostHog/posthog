import { kea, path, selectors } from 'kea'

import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { logsSamplingNewSceneLogicType } from './logsSamplingNewSceneLogicType'

export const logsSamplingNewSceneLogic = kea<logsSamplingNewSceneLogicType>([
    path(['products', 'logs', 'frontend', 'scenes', 'LogsSamplingNewScene', 'logsSamplingNewSceneLogic']),

    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Logs,
                    name: 'Logs',
                    path: `${urls.logs()}?activeTab=configuration&section=environment-logs&setting=logs-sampling`,
                    iconType: 'logs',
                },
                { key: Scene.LogsSamplingNew, name: 'New sampling rule', iconType: 'logs' },
            ],
        ],
    }),
])
