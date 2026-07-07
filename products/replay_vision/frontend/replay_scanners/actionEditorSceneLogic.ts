import { actions, isBreakpoint, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import {
    visionActionsCreate,
    visionActionsPartialUpdate,
    visionActionsRetrieve,
    visionScannersRetrieve,
} from '../generated/api'
import type { VisionActionApi } from '../generated/api.schemas'
import type { actionEditorSceneLogicType } from './actionEditorSceneLogicType'
import { parseRruleToCadence } from './cadence'
import { visionActionRunsLogic } from './visionActionRunsLogic'
import { buildActionBody, NEW_ACTION_FORM, VisionActionForm, visionActionsLogic } from './visionActionsLogic'

export const actionEditorSceneLogic = kea<actionEditorSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'actionEditorSceneLogic']),

    actions({
        setScannerId: (scannerId: string) => ({ scannerId }),
        setScannerName: (scannerName: string) => ({ scannerName }),
        setActionId: (actionId: string) => ({ actionId }),
        loadAction: (actionId: string) => ({ actionId }),
        loadActionSuccess: (action: VisionActionApi) => ({ action }),
        loadActionFailure: true,
    }),

    reducers({
        // Known up-front for a new action (URL param); filled in from the loaded action when editing.
        scannerId: [
            '',
            {
                setScannerId: (_, { scannerId }) => scannerId,
            },
        ],
        // Display-only: the bound scanner's name, for the page title. Fetched whenever the scanner is known.
        scannerName: [
            '',
            {
                setScannerId: () => '',
                setScannerName: (_, { scannerName }) => scannerName,
            },
        ],
        actionId: [
            'new' as string,
            {
                setActionId: (_, { actionId }) => actionId,
            },
        ],
        loadedAction: [
            null as VisionActionApi | null,
            {
                setActionId: () => null,
                loadActionSuccess: (_, { action }) => action,
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
        isNew: [(s) => [s.actionId], (actionId: string): boolean => actionId === 'new'],
        // The scanner the create/update body targets: loaded action's scanner when editing, else the URL's.
        effectiveScannerId: [
            (s) => [s.scannerId, s.loadedAction],
            (scannerId: string, loadedAction: VisionActionApi | null): string => loadedAction?.scanner || scannerId,
        ],
        breadcrumbs: [
            (s) => [s.isNew, s.actionId, s.effectiveScannerId, s.loadedAction, s.scannerName],
            (
                isNew: boolean,
                actionId: string,
                effectiveScannerId: string,
                loadedAction: VisionActionApi | null,
                scannerName: string
            ): Breadcrumb[] => {
                const crumbs: Breadcrumb[] = [
                    {
                        key: 'replay-vision',
                        name: 'Replay vision',
                        path: urls.replayVision(),
                        iconType: 'replay_vision',
                    },
                ]
                if (isNew) {
                    if (effectiveScannerId) {
                        crumbs.push({
                            key: `scanner-${effectiveScannerId}`,
                            name: scannerName || 'Scanner',
                            path: `${urls.replayVision(effectiveScannerId)}?tab=actions`,
                        })
                    }
                    crumbs.push({ key: 'new-action', name: 'New summary' })
                    return crumbs
                }
                crumbs.push(
                    {
                        key: `action-${actionId}`,
                        name: loadedAction?.name || 'Summary',
                        path: urls.replayVisionAction(actionId),
                    },
                    { key: `action-${actionId}-edit`, name: 'Edit' }
                )
                return crumbs
            },
        ],
    }),

    forms(({ values }) => ({
        actionForm: {
            defaults: NEW_ACTION_FORM(),
            errors: ({ name, cadence, integration_id, channel, min_score, max_score }: VisionActionForm) => ({
                name: !name?.trim() ? 'Give this summary a name' : undefined,
                // kea-forms can't carry a string error on the weekdays array, so hang it on `hour` to
                // mark the form invalid and block Enter-to-submit; the visible copy is the inline text.
                cadence: cadence.weekdays.length === 0 ? { hour: 'Pick at least one day' } : undefined,
                channel: integration_id && !channel ? 'Pick a channel' : undefined,
                min_score:
                    min_score != null && max_score != null && min_score > max_score
                        ? "Min score can't exceed max score"
                        : undefined,
            }),
            submit: async (form: VisionActionForm) => {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    throw new Error('No team selected')
                }
                const scannerId = values.effectiveScannerId
                if (!scannerId) {
                    throw new Error('No scanner selected')
                }
                const body = buildActionBody(form, scannerId)
                if (values.isNew) {
                    const created = await visionActionsCreate(String(teamId), body)
                    lemonToast.success('Summary created')
                    visionActionsLogic.findMounted({ scannerId })?.actions.loadActions()
                    router.actions.push(urls.replayVisionAction(created.id))
                    return
                }
                const updated = await visionActionsPartialUpdate(String(teamId), values.actionId, body)
                lemonToast.success('Summary updated')
                visionActionsLogic.findMounted({ scannerId })?.actions.loadActions()
                const runsLogic = visionActionRunsLogic.findMounted({ actionId: updated.id })
                runsLogic?.actions.loadAction()
                runsLogic?.actions.loadRuns()
                router.actions.push(urls.replayVisionAction(updated.id))
            },
        },
    })),

    listeners(({ actions, values }) => ({
        setScannerId: async ({ scannerId }, breakpoint) => {
            // Only fetch the scanner name on the new-action route — the edit title uses the action name instead.
            if (!values.isNew) {
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!scannerId || !teamId) {
                return
            }
            try {
                const scanner = await visionScannersRetrieve(String(teamId), scannerId)
                breakpoint()
                actions.setScannerName(scanner.name)
            } catch {
                // Display-only — the title falls back to "New summary".
            }
        },

        loadAction: async ({ actionId }, breakpoint) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.loadActionFailure()
                return
            }
            try {
                const action = await visionActionsRetrieve(String(teamId), actionId)
                breakpoint()
                actions.loadActionSuccess(action)
            } catch (error: any) {
                if (isBreakpoint(error)) {
                    throw error
                }
                lemonToast.error(`Failed to load summary${error.detail ? `: ${error.detail}` : ''}`)
                actions.loadActionFailure()
            }
        },

        loadActionSuccess: ({ action }) => {
            actions.setScannerId(action.scanner)
            actions.setActionFormValues({
                name: action.name,
                cadence: parseRruleToCadence(action.trigger_config?.rrule),
                timezone: action.trigger_config?.timezone || dayjs.tz.guess(),
                prompt_guide: action.synthesis_config?.prompt_guide ?? '',
                integration_id: action.delivery_config?.[0]?.integration_id ?? null,
                channel: action.delivery_config?.[0]?.channel ?? '',
                verdict: action.selection?.verdict ?? [],
                tags: action.selection?.tags ?? [],
                min_score: action.selection?.min_score ?? null,
                max_score: action.selection?.max_score ?? null,
            })
        },

        submitActionFormFailure: ({ error }: { error?: Error & { detail?: string } }) => {
            lemonToast.error(`Failed to save summary${error?.detail ? `: ${error.detail}` : ''}`)
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.replayVisionActionNew(':scannerId')]: ({ scannerId }) => {
            actions.setActionId('new')
            actions.setScannerId(scannerId || '')
            actions.resetActionForm(NEW_ACTION_FORM()) // clear values left from a previous edit
        },
        [urls.replayVisionActionEdit(':actionId')]: ({ actionId }) => {
            const id = actionId || 'new'
            actions.setActionId(id)
            actions.loadAction(id)
        },
    })),
])
