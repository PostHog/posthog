import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { visionActionsRetrieve, visionActionsRunsList } from '../generated/api'
import type { VisionActionApi, VisionActionRunListApi } from '../generated/api.schemas'
import type { visionActionRunsLogicType } from './visionActionRunsLogicType'
import { visionActionSceneLogic } from './visionActionSceneLogic'

export interface VisionActionRunsLogicProps {
    actionId: string
}

export const visionActionRunsLogic = kea<visionActionRunsLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionActionRunsLogic']),
    props({} as VisionActionRunsLogicProps),
    key((props) => props.actionId),

    actions({
        loadRuns: true,
        loadRunsSuccess: (runs: VisionActionRunListApi[], count: number) => ({ runs, count }),
        loadRunsFailure: true,
        loadAction: true,
        loadActionSuccess: (action: VisionActionApi) => ({ action }),
        loadActionFailure: true,
    }),

    reducers({
        runs: [
            [] as VisionActionRunListApi[],
            {
                loadRunsSuccess: (_, { runs }) => runs,
            },
        ],
        runsCount: [
            0,
            {
                loadRunsSuccess: (_, { count }) => count,
            },
        ],
        // Loading starts true so the page shows a spinner, not a flash of "no runs", before the first fetch.
        runsLoading: [
            true,
            {
                loadRuns: () => true,
                loadRunsSuccess: () => false,
                loadRunsFailure: () => false,
            },
        ],
        action: [
            null as VisionActionApi | null,
            {
                loadActionSuccess: (_, { action }) => action,
            },
        ],
        actionLoading: [
            true,
            {
                loadAction: () => true,
                loadActionSuccess: () => false,
                loadActionFailure: () => false,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        loadRuns: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.loadRunsFailure()
                return
            }
            try {
                const response = await visionActionsRunsList(String(teamId), props.actionId, { limit: 100 })
                actions.loadRunsSuccess(response.results ?? [], response.count ?? response.results?.length ?? 0)
            } catch (error: any) {
                lemonToast.error(`Failed to load runs${error.detail ? `: ${error.detail}` : ''}`)
                actions.loadRunsFailure()
            }
        },

        // Loads the action metadata for the page title + breadcrumb. Runs render independently of this.
        loadAction: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.loadActionFailure()
                return
            }
            try {
                const action = await visionActionsRetrieve(String(teamId), props.actionId)
                actions.loadActionSuccess(action)
                visionActionSceneLogic.actions.setActionContext(action.name, action.scanner ?? null)
            } catch {
                actions.loadActionFailure()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRuns()
        actions.loadAction()
    }),
])
