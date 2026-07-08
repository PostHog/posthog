import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    visionActionsCreate,
    visionActionsDestroy,
    visionActionsList,
    visionActionsPartialUpdate,
} from '../generated/api'
import { DeliveryTargetTypeEnumApi } from '../generated/api.schemas'
import type { VisionActionApi } from '../generated/api.schemas'
import { CadenceState, cadenceToRrule, DEFAULT_CADENCE, parseRruleToCadence } from './cadence'
import { visionActionRunsLogic } from './visionActionRunsLogic'
import type { visionActionsLogicType } from './visionActionsLogicType'

export interface VisionActionsLogicProps {
    scannerId: string
}

// UI-shaped form values, mapped to/from the API shape on submit/edit.
export interface VisionActionForm {
    name: string
    cadence: CadenceState
    timezone: string
    prompt_guide: string
    integration_id: number | null
    channel: string
}

const NEW_ACTION_FORM = (): VisionActionForm => ({
    name: '',
    cadence: { ...DEFAULT_CADENCE },
    timezone: dayjs.tz.guess(),
    prompt_guide: '',
    integration_id: null,
    channel: '',
})

// Map the UI form shape to the API body shared by create + partial-update. Kept standalone so the
// rrule + delivery-target mapping (the part most likely to grow beyond a single Slack target) is
// unit-testable without the form machinery.
export function buildActionBody(form: VisionActionForm, scannerId: string): Parameters<typeof visionActionsCreate>[1] {
    return {
        name: form.name.trim(),
        scanner: scannerId,
        trigger_config: { rrule: cadenceToRrule(form.cadence), timezone: form.timezone },
        synthesis_config: { prompt_guide: form.prompt_guide },
        delivery_config:
            form.integration_id && form.channel
                ? [
                      {
                          type: DeliveryTargetTypeEnumApi.Slack,
                          integration_id: form.integration_id,
                          // Store the `${id}|#${name}` picker composite so the table can show the
                          // channel name; delivery.py strips it to the bare id for the Slack destination.
                          channel: form.channel,
                      },
                  ]
                : [],
    }
}

export const visionActionsLogic = kea<visionActionsLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'visionActionsLogic']),
    props({} as VisionActionsLogicProps),
    key((props) => props.scannerId),

    actions({
        loadActions: true,
        loadActionsSuccess: (visionActions: VisionActionApi[]) => ({ visionActions }),
        loadActionsFailure: true,
        toggleActionEnabled: (id: string) => ({ id }),
        revertActionEnabled: (id: string) => ({ id }),
        toggleActionEnabledDone: (id: string) => ({ id }),
        deleteAction: (id: string) => ({ id }),
        deleteActionSuccess: (id: string) => ({ id }),
        openCreateForm: true,
        openEditForm: (action: VisionActionApi) => ({ action }),
        closeForm: true,
    }),

    reducers({
        visionActions: [
            [] as VisionActionApi[],
            {
                loadActionsSuccess: (_, { visionActions }) => visionActions,
                deleteActionSuccess: (state, { id }) => state.filter((a) => a.id !== id),
                // Optimistic flip on toggle; revert mirrors it back on failure.
                toggleActionEnabled: (state, { id }) =>
                    state.map((a) => (a.id === id ? { ...a, enabled: !a.enabled } : a)),
                revertActionEnabled: (state, { id }) =>
                    state.map((a) => (a.id === id ? { ...a, enabled: !a.enabled } : a)),
            },
        ],
        visionActionsLoading: [
            false,
            {
                loadActions: () => true,
                loadActionsSuccess: () => false,
                loadActionsFailure: () => false,
            },
        ],
        togglingIds: [
            [] as string[],
            {
                toggleActionEnabled: (state, { id }) => [...state, id],
                toggleActionEnabledDone: (state, { id }) => state.filter((i) => i !== id),
                revertActionEnabled: (state, { id }) => state.filter((i) => i !== id),
            },
        ],
        formVisible: [
            false,
            {
                openCreateForm: () => true,
                openEditForm: () => true,
                closeForm: () => false,
            },
        ],
        editingAction: [
            null as VisionActionApi | null,
            {
                openCreateForm: () => null,
                openEditForm: (_, { action }) => action,
                closeForm: () => null,
            },
        ],
    }),

    forms(({ props, values }) => ({
        visionActionForm: {
            defaults: NEW_ACTION_FORM(),
            errors: ({ name, cadence, integration_id, channel }) => ({
                name: !name?.trim() ? 'Give this action a name' : undefined,
                // weekdays is a number[], which kea-forms can't carry a string error on, so we hang
                // the "pick a day" error on the cadence object via `hour` to mark the form invalid.
                // This blocks Enter-to-submit (enableFormOnSubmit); the user-facing message is the
                // inline danger text + the submit button's disabledReason.
                cadence: cadence.weekdays.length === 0 ? { hour: 'Pick at least one day' } : undefined,
                channel: integration_id && !channel ? 'Pick a channel' : undefined,
            }),
            submit: async (form) => {
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    throw new Error('No team selected')
                }
                const body = buildActionBody(form, props.scannerId)
                const editing = values.editingAction
                if (editing) {
                    await visionActionsPartialUpdate(String(teamId), editing.id, body)
                } else {
                    await visionActionsCreate(String(teamId), body)
                }
            },
        },
    })),

    listeners(({ actions, props, values }) => ({
        loadActions: async () => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionActionsList(String(teamId), { scanner: props.scannerId, limit: 100 })
                actions.loadActionsSuccess(response.results ?? [])
            } catch (error: any) {
                lemonToast.error(`Failed to load actions${error.detail ? `: ${error.detail}` : ''}`)
                actions.loadActionsFailure()
            }
        },

        toggleActionEnabled: async ({ id }) => {
            // The reducer has already flipped `enabled` optimistically, so this reflects the target state.
            const action = values.visionActions.find((a) => a.id === id)
            const teamId = teamLogic.values.currentTeamId
            if (!action || !teamId) {
                actions.revertActionEnabled(id)
                return
            }
            try {
                await visionActionsPartialUpdate(String(teamId), id, { enabled: action.enabled })
                actions.toggleActionEnabledDone(id)
            } catch (error: any) {
                const verb = action.enabled ? 'enable' : 'disable'
                lemonToast.error(`Failed to ${verb} action${error.detail ? `: ${error.detail}` : ''}`)
                actions.revertActionEnabled(id)
            }
        },

        deleteAction: async ({ id }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                await visionActionsDestroy(String(teamId), id)
                actions.deleteActionSuccess(id)
                lemonToast.success('Action deleted')
            } catch (error: any) {
                lemonToast.error(`Failed to delete action${error.detail ? `: ${error.detail}` : ''}`)
            }
        },

        openCreateForm: () => {
            actions.resetVisionActionForm(NEW_ACTION_FORM())
        },

        openEditForm: ({ action }) => {
            actions.setVisionActionFormValues({
                name: action.name,
                cadence: parseRruleToCadence(action.trigger_config?.rrule),
                timezone: action.trigger_config?.timezone || dayjs.tz.guess(),
                prompt_guide: action.synthesis_config?.prompt_guide ?? '',
                integration_id: action.delivery_config?.[0]?.integration_id ?? null,
                channel: action.delivery_config?.[0]?.channel ?? '',
            })
        },

        closeForm: () => {
            actions.resetVisionActionForm(NEW_ACTION_FORM())
        },

        submitVisionActionFormSuccess: () => {
            // Capture before closeForm() clears editingAction.
            const edited = values.editingAction
            lemonToast.success(edited ? 'Action updated' : 'Action created')
            actions.closeForm()
            actions.loadActions()
            // If this edit came from the action's own page, refresh it in place. findMounted acts only
            // when that page is open (returns null otherwise) — no key coupling, no accidental mount.
            if (edited) {
                const runsLogic = visionActionRunsLogic.findMounted({ actionId: edited.id })
                runsLogic?.actions.loadAction()
                runsLogic?.actions.loadRuns()
            }
        },

        submitVisionActionFormFailure: ({ error }: { error?: Error & { detail?: string } }) => {
            lemonToast.error(`Failed to save action${error?.detail ? `: ${error.detail}` : ''}`)
        },
    })),

    afterMount(({ actions }) => {
        actions.loadActions()
    }),
])
