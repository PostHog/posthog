import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionActionsRunsList } from '../generated/api'
import type { VisionActionRunApi } from '../generated/api.schemas'
import type { visionActionRunsLogicType } from './visionActionRunsLogicType'

export interface VisionActionRunsLogicProps {
    actionId: string
}

export const visionActionRunsLogic = kea<visionActionRunsLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionActionRunsLogic']),
    props({} as VisionActionRunsLogicProps),
    key((props) => props.actionId),

    actions({
        loadRuns: true,
        loadRunsSuccess: (runs: VisionActionRunApi[]) => ({ runs }),
        loadRunsFailure: true,
    }),

    reducers({
        runs: [
            [] as VisionActionRunApi[],
            {
                loadRunsSuccess: (_, { runs }) => runs,
            },
        ],
        runsLoading: [
            false,
            {
                loadRuns: () => true,
                loadRunsSuccess: () => false,
                loadRunsFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        loadRuns: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionActionsRunsList(String(teamId), props.actionId, { limit: 100 })
                actions.loadRunsSuccess(response.results ?? [])
            } catch (error: any) {
                lemonToast.error(`Failed to load runs${error.detail ? `: ${error.detail}` : ''}`)
                actions.loadRunsFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRuns()
    }),
])
