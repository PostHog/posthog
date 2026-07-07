import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router, urlToAction } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { visionActionsCreate, visionActionsPartialUpdate, visionActionsRetrieve } from '../generated/api'
import type { VisionActionApi } from '../generated/api.schemas'
import type { actionEditorSceneLogicType } from './actionEditorSceneLogicType'
import { parseRruleToCadence } from './cadence'
import { visionActionRunsLogic } from './visionActionRunsLogic'
import { buildActionBody, NEW_ACTION_FORM, VisionActionForm, visionActionsLogic } from './visionActionsLogic'

export const actionEditorSceneLogic = kea<actionEditorSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'actionEditorSceneLogic']),

    actions({
        setScannerId: (scannerId: string) => ({ scannerId }),
        setActionId: (actionId: string) => ({ actionId }),
        loadAction: (actionId: string) => ({ actionId }),
        loadActionSuccess: (action: VisionActionApi) => ({ action }),
        loadActionFailure: true,
    }),

    reducers({
        // The scanner the action belongs to. Known up-front for a new action (URL param); for an edit it's
        // filled in once the action loads.
        scannerId: [
            '',
            {
                setScannerId: (_, { scannerId }) => scannerId,
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
        // The scanner the create/update body targets: the loaded action's scanner when editing, else the
        // scanner from the URL for a new action.
        effectiveScannerId: [
            (s) => [s.scannerId, s.loadedAction],
            (scannerId: string, loadedAction: VisionActionApi | null): string => loadedAction?.scanner || scannerId,
        ],
        breadcrumbs: [
            (s) => [s.isNew, s.actionId, s.effectiveScannerId, s.loadedAction],
            (
                isNew: boolean,
                actionId: string,
                effectiveScannerId: string,
                loadedAction: VisionActionApi | null
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
                            name: 'Scanner',
                            path: `${urls.replayVision(effectiveScannerId)}?tab=actions`,
                        })
                    }
                    crumbs.push({ key: 'new-action', name: 'New action' })
                    return crumbs
                }
                crumbs.push(
                    {
                        key: `action-${actionId}`,
                        name: loadedAction?.name || 'Action',
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
            errors: ({ name, cadence, integration_id, channel }: VisionActionForm) => ({
                name: !name?.trim() ? 'Give this action a name' : undefined,
                // weekdays is a number[], which kea-forms can't carry a string error on, so we hang the
                // "pick a day" error on the cadence object via `hour` to mark the form invalid. This blocks
                // Enter-to-submit; the user-facing message is the inline danger text + submit disabledReason.
                cadence: cadence.weekdays.length === 0 ? { hour: 'Pick at least one day' } : undefined,
                channel: integration_id && !channel ? 'Pick a channel' : undefined,
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
                    lemonToast.success('Action created')
                    visionActionsLogic.findMounted({ scannerId })?.actions.loadActions()
                    router.actions.push(urls.replayVisionAction(created.id))
                    return
                }
                const updated = await visionActionsPartialUpdate(String(teamId), values.actionId, body)
                lemonToast.success('Action updated')
                visionActionsLogic.findMounted({ scannerId })?.actions.loadActions()
                const runsLogic = visionActionRunsLogic.findMounted({ actionId: updated.id })
                runsLogic?.actions.loadAction()
                runsLogic?.actions.loadRuns()
                router.actions.push(urls.replayVisionAction(updated.id))
            },
        },
    })),

    listeners(({ actions }) => ({
        loadAction: async ({ actionId }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.loadActionFailure()
                return
            }
            try {
                const action = await visionActionsRetrieve(String(teamId), actionId)
                actions.loadActionSuccess(action)
            } catch (error: any) {
                lemonToast.error(`Failed to load action${error.detail ? `: ${error.detail}` : ''}`)
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
            })
        },

        submitActionFormFailure: ({ error }: { error?: Error & { detail?: string } }) => {
            lemonToast.error(`Failed to save action${error?.detail ? `: ${error.detail}` : ''}`)
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.replayVisionActionNew(':scannerId')]: ({ scannerId }) => {
            actions.setActionId('new')
            actions.setScannerId(scannerId || '')
            // Landing on the create page fresh — clear any values left from a previous edit.
            actions.resetActionForm(NEW_ACTION_FORM())
        },
        [urls.replayVisionActionEdit(':actionId')]: ({ actionId }) => {
            const id = actionId || 'new'
            if (id !== values.actionId || !values.loadedAction) {
                actions.setActionId(id)
                actions.loadAction(id)
            }
        },
    })),
])
