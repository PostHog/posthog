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
import {
    AlertConfigFrequencyEnumApi,
    VisionActionModeEnumApi,
    VisionAlertDirectionEnumApi,
    VisionAlertMetricEnumApi,
} from '../generated/api.schemas'
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
        setScannerType: (scannerType: string) => ({ scannerType }),
        setActionId: (actionId: string) => ({ actionId }),
        setTargetingMode: (mode: 'all' | 'filtered') => ({ mode }),
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
        // The bound scanner's type — drives which alert condition shapes make sense (summarizers
        // have no verdict/tags/score, so their alerts collapse to "every new summary").
        scannerType: [
            '',
            {
                setScannerId: () => '',
                setScannerType: (_, { scannerType }) => scannerType,
            },
        ],
        actionId: [
            'new' as string,
            {
                setActionId: (_, { actionId }) => actionId,
            },
        ],
        // Whether the summary covers everything or only matching observations. Explicit state (not
        // derived from the filter values) so picking "only matching" shows the controls before any
        // value is chosen.
        targetingMode: [
            'all' as 'all' | 'filtered',
            {
                setTargetingMode: (_, { mode }) => mode,
                setActionId: () => 'all',
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
                    crumbs.push({ key: 'new-action', name: 'New' })
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
            errors: ({
                name,
                cadence,
                min_score,
                max_score,
                mode,
                alert_frequency,
                alert_threshold,
            }: VisionActionForm) => ({
                name: !name?.trim() ? 'Give this summary a name' : undefined,
                // kea-forms can't carry a string error on the weekdays array, so hang it on `hour` to
                // mark the form invalid and block Enter-to-submit; the visible copy is the inline text.
                // Alerts have no schedule UI (checked continuously on every sweep), so weekdays don't apply.
                cadence:
                    mode !== VisionActionModeEnumApi.Alert && cadence.weekdays.length === 0
                        ? { hour: 'Pick at least one day' }
                        : undefined,
                min_score:
                    min_score != null && max_score != null && min_score > max_score
                        ? "Min score can't exceed max score"
                        : undefined,
                alert_threshold:
                    mode === VisionActionModeEnumApi.Alert &&
                    alert_frequency === AlertConfigFrequencyEnumApi.OnBreach &&
                    alert_threshold == null
                        ? 'Set a threshold'
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
                    lemonToast.success(
                        form.mode === VisionActionModeEnumApi.Alert ? 'Alert created' : 'Group summary created'
                    )
                    visionActionsLogic.findMounted({ scannerId })?.actions.loadActions()
                    router.actions.push(urls.replayVisionAction(created.id))
                    return
                }
                const updated = await visionActionsPartialUpdate(String(teamId), values.actionId, body)
                lemonToast.success(
                    form.mode === VisionActionModeEnumApi.Alert ? 'Alert updated' : 'Group summary updated'
                )
                visionActionsLogic.findMounted({ scannerId })?.actions.loadActions()
                const runsLogic = visionActionRunsLogic.findMounted({ actionId: updated.id })
                runsLogic?.actions.loadAction()
                runsLogic?.actions.loadRuns()
                router.actions.push(urls.replayVisionAction(updated.id))
            },
        },
    })),

    listeners(({ actions, values }) => ({
        setTargetingMode: ({ mode }) => {
            if (mode === 'all') {
                // Clear the filter values so a hidden filter can't silently narrow the summary.
                actions.setActionFormValues({ verdict: [], tags: [], min_score: null, max_score: null })
            }
        },

        setScannerId: async ({ scannerId }, breakpoint) => {
            // Fetched on both routes: the new-action title needs the name, and alert-condition
            // normalization needs the scanner type (see setScannerType below).
            const teamId = teamLogic.values.currentTeamId
            if (!scannerId || !teamId) {
                return
            }
            try {
                const scanner = await visionScannersRetrieve(String(teamId), scannerId)
                breakpoint()
                actions.setScannerName(scanner.name)
                actions.setScannerType(scanner.scanner_type)
            } catch {
                // Display-only — the title falls back to "New summary".
            }
        },

        setScannerType: ({ scannerType }) => {
            // Summarizer observations carry no verdict/tags/score, so threshold alerts don't apply:
            // their alerts are always "every new summary". Normalizing the form (not just the UI)
            // keeps validation and the submitted alert_config consistent with what the editor shows.
            if (scannerType === 'summarizer' && values.actionForm.mode === VisionActionModeEnumApi.Alert) {
                actions.setActionFormValues({
                    alert_frequency: AlertConfigFrequencyEnumApi.EveryMatch,
                    alert_metric: VisionAlertMetricEnumApi.Count,
                })
            }
        },

        setActionFormValue: ({ name, value }) => {
            // Switching an existing action to alert mode on a summarizer scanner gets the same
            // normalization as loading one.
            if (name === 'mode' && value === VisionActionModeEnumApi.Alert && values.scannerType === 'summarizer') {
                actions.setActionFormValues({
                    alert_frequency: AlertConfigFrequencyEnumApi.EveryMatch,
                    alert_metric: VisionAlertMetricEnumApi.Count,
                })
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
            const selection = action.selection
            const hasFilter = !!(
                selection?.verdict?.length ||
                selection?.tags?.length ||
                selection?.min_score != null ||
                selection?.max_score != null
            )
            actions.setTargetingMode(hasFilter ? 'filtered' : 'all')
            actions.setActionFormValues({
                name: action.name,
                cadence: parseRruleToCadence(action.trigger_config?.rrule),
                timezone: action.trigger_config?.timezone || dayjs.tz.guess(),
                prompt_guide: action.synthesis_config?.prompt_guide ?? '',
                integration_id: action.delivery_config?.[0]?.integration_id ?? null,
                channel: action.delivery_config?.[0]?.channel ?? '',
                mode: action.mode ?? VisionActionModeEnumApi.GroupSummary,
                // Stored alerts without a frequency predate the field and behaved as on_breach; anything
                // else gets the fresh-form default so flipping a summary to an alert starts at every_match.
                alert_frequency:
                    action.alert_config?.frequency ??
                    (action.mode === VisionActionModeEnumApi.Alert
                        ? AlertConfigFrequencyEnumApi.OnBreach
                        : AlertConfigFrequencyEnumApi.EveryMatch),
                alert_metric: action.alert_config?.metric ?? VisionAlertMetricEnumApi.Count,
                alert_threshold: action.alert_config?.threshold ?? 1,
                alert_direction: action.alert_config?.direction ?? VisionAlertDirectionEnumApi.Above,
                alert_window_days: action.alert_config?.window_days ?? 1,
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
