import { actions, kea, path, props } from 'kea'

import type { LinearIntegrationLogicType } from './linearIntegrationLogicType'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

export interface LinearIntegrationLogicProps {}

export const LinearIntegrationLogic = kea<LinearIntegrationLogicType>([
    path(['scenes', 'error-tracking', 'linearIntegrationLogic']),
    props({} as LinearIntegrationLogicProps),

    actions({
        loadAllLinearTeams: () => ({}),
    }),

    loaders(({ props }) => ({
        linearTeams: [
            [] as any[],
            {
                loadAllLinearTeams: async () => {
                    return await api.integrations.linearTeams(props.id)
                },
            },
        ],
    })),
])
