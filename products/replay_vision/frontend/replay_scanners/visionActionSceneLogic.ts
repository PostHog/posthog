import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { visionActionsRetrieve } from '../generated/api'
import type { VisionActionApi } from '../generated/api.schemas'
import type { visionActionSceneLogicType } from './visionActionSceneLogicType'

export const visionActionSceneLogic = kea<visionActionSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionActionSceneLogic']),

    actions({
        setActionId: (actionId: string) => ({ actionId }),
        loadAction: true,
        loadActionSuccess: (action: VisionActionApi) => ({ action }),
        loadActionFailure: true,
    }),

    reducers({
        actionId: [
            '' as string,
            {
                setActionId: (_, { actionId }) => actionId,
            },
        ],
        action: [
            null as VisionActionApi | null,
            {
                loadActionSuccess: (_, { action }) => action,
                // Clear when navigating to a different action so the previous one doesn't flash.
                setActionId: () => null,
            },
        ],
        actionLoading: [
            false,
            {
                loadAction: () => true,
                loadActionSuccess: () => false,
                loadActionFailure: () => false,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.action, s.actionId],
            (action: VisionActionApi | null, actionId: string): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = [
                    {
                        key: 'replay-vision',
                        name: 'Replay vision',
                        path: urls.replayVision(),
                        iconType: 'replay_vision',
                    },
                ]
                if (action?.scanner) {
                    breadcrumbs.push({
                        key: `scanner-${action.scanner}`,
                        name: 'Scanner',
                        path: `${urls.replayVision(action.scanner)}?tab=actions`,
                    })
                }
                breadcrumbs.push({
                    key: actionId ? `action-${actionId}` : 'action',
                    name: action?.name || 'Action',
                    path: urls.replayVisionAction(actionId),
                })
                return breadcrumbs
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadAction: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId || !values.actionId) {
                return
            }
            try {
                const action = await visionActionsRetrieve(String(teamId), values.actionId)
                actions.loadActionSuccess(action)
            } catch (error: any) {
                if (error.status !== 404) {
                    lemonToast.error(`Failed to load action${error.detail ? `: ${error.detail}` : ''}`)
                }
                actions.loadActionFailure()
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.replayVisionAction(':actionId')]: ({ actionId }) => {
            const next = actionId || ''
            if (next !== values.actionId) {
                actions.setActionId(next)
                actions.loadAction()
            }
        },
    })),
])
