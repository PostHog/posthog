import { afterMount, connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { logsSamplingRulesList } from 'products/logs/frontend/generated/api'
import { LogsSamplingRuleApi } from 'products/logs/frontend/generated/api.schemas'

import type { logsSamplingSectionLogicType } from './logsSamplingSectionLogicType'

export const logsSamplingSectionLogic = kea<logsSamplingSectionLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsSampling', 'logsSamplingSectionLogic']),

    connect({
        values: [teamLogic, ['currentTeamId']],
    }),

    loaders(({ values }) => ({
        rules: [
            [] as LogsSamplingRuleApi[],
            {
                loadRules: async () => {
                    const projectId = String(values.currentTeamId)
                    const page = await logsSamplingRulesList(projectId)
                    return page.results
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadRules()
    }),
])
