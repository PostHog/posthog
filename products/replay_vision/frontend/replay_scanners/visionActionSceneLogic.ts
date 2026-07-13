import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { visionActionSceneLogicType } from './visionActionSceneLogicType'

export const visionActionSceneLogic = kea<visionActionSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionActionSceneLogic']),

    actions({
        setActionId: (actionId: string) => ({ actionId }),
        // Pushed by visionActionRunsLogic once the action loads, so the title + breadcrumb can resolve.
        setActionContext: (name: string | null, scannerId: string | null) => ({ name, scannerId }),
    }),

    reducers({
        actionId: [
            '' as string,
            {
                setActionId: (_, { actionId }) => actionId,
            },
        ],
        actionContext: [
            { name: null, scannerId: null } as { name: string | null; scannerId: string | null },
            {
                setActionContext: (_, { name, scannerId }) => ({ name, scannerId }),
                // Clear when navigating to a different action so the previous one doesn't linger.
                setActionId: () => ({ name: null, scannerId: null }),
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.actionId, s.actionContext],
            (actionId: string, context: { name: string | null; scannerId: string | null }): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = [
                    {
                        key: 'replay-vision',
                        name: 'Replay vision',
                        path: urls.replayVision(),
                        iconType: 'replay_vision',
                    },
                ]
                if (context.scannerId) {
                    breadcrumbs.push({
                        key: `scanner-${context.scannerId}`,
                        name: 'Scanner',
                        path: `${urls.replayVision(context.scannerId)}?tab=actions`,
                    })
                }
                breadcrumbs.push({
                    key: actionId ? `action-${actionId}` : 'action',
                    name: context.name || 'Summary',
                    path: urls.replayVisionAction(actionId),
                })
                return breadcrumbs
            },
        ],
    }),

    urlToAction(({ actions, values }) => ({
        [urls.replayVisionAction(':actionId')]: ({ actionId }) => {
            const next = actionId || ''
            if (next !== values.actionId) {
                actions.setActionId(next)
            }
        },
    })),
])
