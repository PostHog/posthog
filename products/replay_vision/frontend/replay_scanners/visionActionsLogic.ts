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
import {
    AlertConfigFrequencyEnumApi,
    DeliveryTargetTypeEnumApi,
    VisionActionModeEnumApi,
    VisionAlertDirectionEnumApi,
    VisionAlertMetricEnumApi,
    WindowDaysEnumApi,
} from '../generated/api.schemas'
import type { VerdictEnumApi, VisionActionApi } from '../generated/api.schemas'
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
    // Targeting ("run this on…") — empty means all of the scanner's observations.
    verdict: VerdictEnumApi[]
    tags: string[]
    min_score: number | null
    max_score: number | null
    // What the action produces; alerts carry a condition instead of synthesizing a summary.
    mode: VisionActionModeEnumApi
    alert_frequency: AlertConfigFrequencyEnumApi
    alert_metric: VisionAlertMetricEnumApi
    alert_threshold: number | null
    alert_direction: VisionAlertDirectionEnumApi
    alert_window_days: WindowDaysEnumApi
}

export const NEW_ACTION_FORM = (): VisionActionForm => ({
    name: '',
    cadence: { ...DEFAULT_CADENCE },
    timezone: dayjs.tz.guess(),
    prompt_guide: '',
    integration_id: null,
    channel: '',
    verdict: [],
    tags: [],
    min_score: null,
    max_score: null,
    mode: VisionActionModeEnumApi.GroupSummary,
    // Default alert flavor: notify about every new match ("every time the result is X, tell me").
    alert_frequency: AlertConfigFrequencyEnumApi.EveryMatch,
    alert_metric: VisionAlertMetricEnumApi.Count,
    alert_threshold: 1,
    alert_direction: VisionAlertDirectionEnumApi.Above,
    alert_window_days: 1,
})

// Map the UI form shape to the API body shared by create + partial-update. Kept standalone so the
// rrule + delivery-target mapping (the part most likely to grow beyond a single Slack target) is
// unit-testable without the form machinery.
export function buildActionBody(form: VisionActionForm, scannerId: string): Parameters<typeof visionActionsCreate>[1] {
    // Always send selection (even empty) so clearing every targeting control on edit persists as
    // "run on everything" rather than silently keeping the previous predicate.
    const selection: NonNullable<Parameters<typeof visionActionsCreate>[1]['selection']> = {}
    if (form.verdict.length) {
        selection.verdict = form.verdict
    }
    if (form.tags.length) {
        selection.tags = form.tags
    }
    if (form.min_score != null) {
        selection.min_score = form.min_score
    }
    if (form.max_score != null) {
        selection.max_score = form.max_score
    }
    const isAlert = form.mode === VisionActionModeEnumApi.Alert
    return {
        name: form.name.trim(),
        scanner: scannerId,
        mode: form.mode,
        // Alerts have no user-facing schedule: the engine checks them on every scanner sweep and
        // ignores this rrule (kept so the trigger stays well-formed); summaries run on the picked days/time.
        trigger_config: isAlert
            ? { rrule: 'FREQ=HOURLY', timezone: form.timezone }
            : { rrule: cadenceToRrule(form.cadence), timezone: form.timezone },
        selection,
        synthesis_config: { prompt_guide: isAlert ? '' : form.prompt_guide },
        ...(isAlert
            ? {
                  alert_config:
                      form.alert_frequency === AlertConfigFrequencyEnumApi.EveryMatch
                          ? { frequency: form.alert_frequency, metric: VisionAlertMetricEnumApi.Count }
                          : {
                                frequency: form.alert_frequency,
                                metric: form.alert_metric,
                                threshold: form.alert_threshold ?? 1,
                                direction: form.alert_direction,
                                window_days: form.alert_window_days,
                            },
              }
            : {}),
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
        addAction: (action: VisionActionApi) => ({ action }),
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
                addAction: (state, { action }) => [...state, action],
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
                lemonToast.error(`Failed to load summaries${error.detail ? `: ${error.detail}` : ''}`)
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
                lemonToast.error(`Failed to ${verb} summary${error.detail ? `: ${error.detail}` : ''}`)
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
                lemonToast.success('Summary deleted')
            } catch (error: any) {
                lemonToast.error(`Failed to delete summary${error.detail ? `: ${error.detail}` : ''}`)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadActions()
    }),
])
