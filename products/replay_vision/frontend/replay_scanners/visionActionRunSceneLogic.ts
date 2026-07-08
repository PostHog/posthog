import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { visionActionsRetrieve, visionActionsRunsRetrieve } from '../generated/api'
import type { RunObservationApi, VisionActionApi, VisionActionRunApi } from '../generated/api.schemas'
import type { visionActionRunSceneLogicType } from './visionActionRunSceneLogicType'

/**
 * Resolve the `[obs N]` citation markers the synthesizer leaves in a group summary into `[N]` links to
 * each observation. `N` is the observation's stable `index` (its position in the summary), so a deleted
 * observation drops its citation rather than misdirecting to a renumbered neighbor.
 */
export function resolveObservationCitations(markdown: string, observations: readonly RunObservationApi[]): string {
    const byIndex = new Map(observations.map((obs) => [obs.index, obs]))
    return markdown.replace(/\[obs (\d+)\]/g, (_match, n: string) => {
        const obs = byIndex.get(Number(n))
        return obs ? `[[${n}]](${urls.replayVisionObservation(obs.id)})` : ''
    })
}

export const visionActionRunSceneLogic = kea<visionActionRunSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionActionRunSceneLogic']),

    actions({
        setIds: (actionId: string, runId: string) => ({ actionId, runId }),
        loadRun: true,
        loadRunSuccess: (run: VisionActionRunApi) => ({ run }),
        loadRunFailure: true,
        loadAction: true,
        loadActionSuccess: (action: VisionActionApi) => ({ action }),
        loadActionFailure: true,
    }),

    reducers({
        actionId: ['', { setIds: (_, { actionId }) => actionId }],
        runId: ['', { setIds: (_, { runId }) => runId }],
        run: [
            null as VisionActionRunApi | null,
            {
                setIds: () => null, // clear when navigating to a different run so the previous one doesn't linger
                loadRunSuccess: (_, { run }) => run,
            },
        ],
        // Starts true so the page shows a spinner, not a flash of "not found", before the first fetch.
        runLoading: [
            true,
            {
                loadRun: () => true,
                loadRunSuccess: () => false,
                loadRunFailure: () => false,
            },
        ],
        action: [
            null as VisionActionApi | null,
            {
                setIds: () => null,
                loadActionSuccess: (_, { action }) => action,
            },
        ],
    }),

    selectors({
        // The synthesized report keeps the raw `[obs N]` citation markers the summarizer emitted; resolve each
        // to a link to that observation so the reader can jump straight to the recording behind a theme.
        summaryMarkdown: [
            (s) => [s.run],
            (run: VisionActionRunApi | null): string =>
                run?.synthesized_markdown
                    ? resolveObservationCitations(run.synthesized_markdown, run.observations)
                    : '',
        ],
        breadcrumbs: [
            (s) => [s.actionId, s.runId, s.action, s.run],
            (
                actionId: string,
                runId: string,
                action: VisionActionApi | null,
                run: VisionActionRunApi | null
            ): Breadcrumb[] => {
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
                    name: action?.name || 'Summary',
                    path: urls.replayVisionAction(actionId),
                })
                breadcrumbs.push({
                    key: runId ? `run-${runId}` : 'run',
                    name: run ? dayjs(run.scheduled_at ?? run.created_at).format('MMM D, YYYY HH:mm') : 'Run',
                    path: urls.replayVisionActionRun(actionId, runId),
                })
                return breadcrumbs
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        loadRun: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId || !values.actionId || !values.runId) {
                actions.loadRunFailure()
                return
            }
            try {
                const run = await visionActionsRunsRetrieve(String(teamId), values.actionId, values.runId)
                actions.loadRunSuccess(run)
            } catch (error: any) {
                // Surface the failure so a transient error isn't silently rendered as "Run not found".
                lemonToast.error(`Failed to load run${error?.detail ? `: ${error.detail}` : ''}`)
                actions.loadRunFailure()
            }
        },
        loadAction: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId || !values.actionId) {
                actions.loadActionFailure()
                return
            }
            try {
                const action = await visionActionsRetrieve(String(teamId), values.actionId)
                actions.loadActionSuccess(action)
            } catch {
                actions.loadActionFailure()
            }
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.replayVisionActionRun(':actionId', ':runId')]: ({ actionId, runId }) => {
            const nextAction = actionId || ''
            const nextRun = runId || ''
            if (!nextAction || !nextRun) {
                return
            }
            if (nextAction !== values.actionId || nextRun !== values.runId) {
                actions.setIds(nextAction, nextRun)
                actions.loadRun()
                actions.loadAction()
            }
        },
    })),
])
