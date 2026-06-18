import { kea, path, selectors } from 'kea'

import { Scene } from 'scenes/sceneTypes'

import { Breadcrumb } from '~/types'

import { logsDropRulesSettingsUrl } from 'products/logs/frontend/logsDropRulesSettingsUrl'

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
                    path: logsDropRulesSettingsUrl(),
                    iconType: 'logs',
                },
                { key: Scene.LogsSamplingNew, name: 'New drop rule', iconType: 'logs' },
            ],
        ],
    }),
])
