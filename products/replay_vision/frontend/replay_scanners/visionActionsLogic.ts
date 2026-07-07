import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

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
import { CadenceState, cadenceToRrule, DEFAULT_CADENCE } from './cadence'
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

export const NEW_ACTION_FORM = (): VisionActionForm => ({
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
    }),

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
    })),

    afterMount(({ actions }) => {
        actions.loadActions()
    }),
])
