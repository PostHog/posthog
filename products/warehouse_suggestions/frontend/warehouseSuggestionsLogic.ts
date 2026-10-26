import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { ApiConfig } from 'lib/api'
import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { EMPTY_INCREMENTAL_DRAFT, IncrementalConfigDraft } from 'scenes/data-warehouse/editor/IncrementalConfigFields'

import { DataModelingSyncInterval } from '~/types'

import {
    warehouseSavedQueriesCheckIncrementalCreate,
    warehouseSavedQueriesRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type { IncrementalEligibilityApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import {
    warehouseSuggestionsAcceptCreate,
    warehouseSuggestionsDismissCreate,
    warehouseSuggestionsList,
    warehouseSuggestionsResumeCreate,
    warehouseSuggestionsStatusRetrieve,
} from './generated/api'
import type {
    AcceptWarehouseSuggestionApi,
    DismissWarehouseSuggestionApi,
    WarehouseSuggestionMaterializePayloadApi,
    WarehouseSuggestionApi,
    WarehouseSuggestionStatusApi,
} from './generated/api.schemas'
import type { WarehouseSuggestionDismissalReasonEnumApi } from './generated/api.schemas'
import { INTERVAL_SECONDS, intervalForSeconds } from './refreshIntervals'
import { subjectUrl } from './subjectUrl'
import {
    MonthlySaving,
    SavingsSummary,
    isMaterializePayload,
    monthlySaving,
    notNowCondition,
    savesTime,
} from './suggestionCopy'

export type StripState = 'loading' | 'error' | 'hidden' | 'warming_up' | 'not_eligible' | 'active' | 'all_done'
export type SuggestionSurface = 'models' | 'catalog'

export interface WarehouseSuggestionsLogicProps {
    surface: SuggestionSurface
    onAccepted?: (suggestion: WarehouseSuggestionApi) => void
    onViewAccepted?: (suggestion: WarehouseSuggestionApi) => void
}

export const ROW_LEAVE_MS = 150
const KIND_ORDER: Record<string, number> = { certify: 0, deprecate: 1 }

const SURFACE_KINDS: Record<SuggestionSurface, string[]> = {
    models: ['materialize', 'unmaterialize'],
    catalog: ['certify', 'deprecate'],
}
const VIEW_ON_MODEL_PAGE_KINDS = ['materialize', 'unmaterialize']
const CONFLICT_STATUS = 409
const NOT_FOUND_STATUS = 404
const FORBIDDEN_STATUS = 403
const PICK_INTERVAL_REASON = 'Pick how often it refreshes'
const INCOMPLETE_INCREMENTAL_REASON = 'Select the incremental column and unique key columns'
const ACCEPTED_MESSAGES: Record<string, (suggestion: WarehouseSuggestionApi) => string> = {
    materialize: ({ payload }) => `Materializing ${payload.subject_name}. The first refresh is running.`,
    unmaterialize: ({ payload }) =>
        `Stopped materializing ${payload.subject_name}. Each read now computes it from its query.`,
    certify: ({ payload }) => `Certified ${payload.subject_name}.`,
    deprecate: ({ payload, created_asset }) =>
        created_asset?.stopped_materialization === true
            ? `Marked ${payload.subject_name} as deprecated and stopped its refreshes.`
            : `Marked ${payload.subject_name} as deprecated.`,
}
const ACCEPT_OPTION_FIELDS = new Set([
    'refresh_interval_seconds',
    'refresh_mode',
    'incremental_key',
    'unique_key',
    'lookback_seconds',
])
const NOT_SUGGESTED_AGAIN = 'Dismissed. Not suggested again.'
const CHECKING_INCREMENTAL_REASON = 'Checking whether it can refresh incrementally'

function dismissedMessage(reason: DismissWarehouseSuggestionApi['reason'], kind: string): string {
    return reason === 'not_now' ? `Dismissed. ${notNowCondition(kind)}` : NOT_SUGGESTED_AGAIN
}

function suggestionWorth(suggestion: WarehouseSuggestionApi): [number, number] {
    const saving = monthlySaving(suggestion.payload)
    if (!saving) {
        return [KIND_ORDER[suggestion.kind] ?? 0, 0]
    }
    return savesTime(saving) ? [0, -saving.seconds] : [1, -saving.bytes]
}

function compareSuggestions(a: WarehouseSuggestionApi, b: WarehouseSuggestionApi): number {
    const [groupA, valueA] = suggestionWorth(a)
    const [groupB, valueB] = suggestionWorth(b)
    return groupA - groupB || valueA - valueB
}

function proposedRefreshDraft(payload: WarehouseSuggestionMaterializePayloadApi): IncrementalConfigDraft {
    return {
        enabled: payload.refresh_mode === 'incremental',
        incrementalKey: payload.incremental_key ?? null,
        uniqueKey: payload.unique_key ?? [],
        lookbackSeconds: payload.lookback_seconds ?? 0,
    }
}

function changedRefreshOptions(
    payload: WarehouseSuggestionMaterializePayloadApi,
    draft: IncrementalConfigDraft
): AcceptWarehouseSuggestionApi {
    const proposed = proposedRefreshDraft(payload)
    const options: AcceptWarehouseSuggestionApi = {}
    if (draft.enabled !== proposed.enabled) {
        options.refresh_mode = draft.enabled ? 'incremental' : 'full'
    }
    if (!draft.enabled) {
        return options
    }
    const switchedToIncremental = !proposed.enabled
    if (draft.incrementalKey && (switchedToIncremental || draft.incrementalKey !== proposed.incrementalKey)) {
        options.incremental_key = draft.incrementalKey
    }
    if (
        draft.uniqueKey.length > 0 &&
        (switchedToIncremental || draft.uniqueKey.join(',') !== proposed.uniqueKey.join(','))
    ) {
        options.unique_key = draft.uniqueKey
    }
    if (switchedToIncremental || draft.lookbackSeconds !== proposed.lookbackSeconds) {
        options.lookback_seconds = draft.lookbackSeconds
    }
    return options
}

async function fetchIncrementalCheck(viewId: string): Promise<IncrementalEligibilityApi | null> {
    try {
        const view = await warehouseSavedQueriesRetrieve(projectId(), viewId)
        return await warehouseSavedQueriesCheckIncrementalCreate(projectId(), { query: view.query.query })
    } catch {
        return null
    }
}

function sum(values: number[]): number {
    return values.reduce((total, value) => total + value, 0)
}

function leaveDisposableKey(id: string): string {
    return `leave-${id}`
}

function projectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface warehouseSuggestionsLogicValues {
    acceptConfirmSuggestion: WarehouseSuggestionApi | null
    acceptConfirmSuggestionId: string | null
    actionsInFlight: Record<string, boolean>
    featureForbidden: boolean
    hiddenSuggestionIds: string[]
    incrementalCheck: IncrementalEligibilityApi | null
    incrementalCheckLoading: boolean
    keepMaterialized: boolean
    leavingSuggestionIds: string[]
    listedSuggestions: WarehouseSuggestionApi[]
    loadError: boolean
    materializeDisabledReason: string | null
    materializeError: string | null
    materializeInterval: DataModelingSyncInterval | null
    materializeIntervalShorterThanSuggested: boolean
    materializeModalSuggestion: WarehouseSuggestionApi | null
    materializeModalSuggestionId: string | null
    refreshDraft: IncrementalConfigDraft
    reviewOpen: boolean
    savingsSummary: SavingsSummary
    status: WarehouseSuggestionStatusApi | null
    statusLoading: boolean
    stripState: StripState
    suggestions: WarehouseSuggestionApi[] | null
    suggestionsLoading: boolean
    surfaceSuggestions: WarehouseSuggestionApi[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface warehouseSuggestionsLogicActions {
    acceptSuggestion: (
        id: string,
        options?: AcceptWarehouseSuggestionApi
    ) => {
        id: string
        options: AcceptWarehouseSuggestionApi | undefined
    }
    acceptSuggestionFailed: (id: string) => {
        id: string
    }
    closeAcceptConfirm: () => {
        value: true
    }
    closeMaterializeModal: () => {
        value: true
    }
    closeMaterializeModalFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    closeMaterializeModalSuccess: (
        incrementalCheck: null,
        payload?: {
            value: true
        }
    ) => {
        incrementalCheck: null
        payload?: {
            value: true
        }
    }
    closeReview: () => {
        value: true
    }
    confirmAccept: () => {
        value: true
    }
    confirmMaterialize: () => {
        value: true
    }
    dismissSuggestion: (
        id: string,
        reason: DismissWarehouseSuggestionApi['reason'],
        note?: string
    ) => {
        id: string
        note: string | undefined
        reason: WarehouseSuggestionDismissalReasonEnumApi
    }
    finishHidingSuggestion: (id: string) => {
        id: string
    }
    hideSuggestion: (id: string) => {
        id: string
    }
    loadIncrementalCheck: (viewId: string) => string
    loadIncrementalCheckFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadIncrementalCheckSuccess: (
        incrementalCheck: IncrementalEligibilityApi | null,
        payload?: string
    ) => {
        incrementalCheck: IncrementalEligibilityApi | null
        payload?: string
    }
    loadStatus: () => any
    loadStatusFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadStatusSuccess: (
        status: WarehouseSuggestionStatusApi,
        payload?: any
    ) => {
        status: WarehouseSuggestionStatusApi
        payload?: any
    }
    loadSuggestions: () => any
    loadSuggestionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSuggestionsSuccess: (
        suggestions: WarehouseSuggestionApi[],
        payload?: any
    ) => {
        suggestions: WarehouseSuggestionApi[]
        payload?: any
    }
    openAcceptConfirm: (id: string) => {
        id: string
    }
    openMaterializeModal: (id: string) => {
        id: string
    }
    openReview: () => {
        value: true
    }
    reload: () => {
        value: true
    }
    restoreSuggestion: (id: string) => {
        id: string
    }
    setActionInFlight: (
        id: string,
        inFlight: boolean
    ) => {
        id: string
        inFlight: boolean
    }
    setKeepMaterialized: (keepMaterialized: boolean) => {
        keepMaterialized: boolean
    }
    setMaterializeError: (error: string | null) => {
        error: string | null
    }
    setMaterializeInterval: (interval: DataModelingSyncInterval | null) => {
        interval: DataModelingSyncInterval | null
    }
    setRefreshDraft: (draft: Partial<IncrementalConfigDraft>) => {
        draft: Partial<IncrementalConfigDraft>
    }
    suggestionAccepted: (suggestion: WarehouseSuggestionApi) => {
        suggestion: WarehouseSuggestionApi
    }
    suggestionResumed: (suggestion: WarehouseSuggestionApi) => {
        suggestion: WarehouseSuggestionApi
    }
    undoDismiss: (id: string) => {
        id: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface warehouseSuggestionsLogicMeta {
    key: SuggestionSurface
    __keaTypeGenInternalSelectorTypes: {
        listedSuggestions: (
            suggestions: WarehouseSuggestionApi[] | null,
            hiddenSuggestionIds: string[],
            surface: SuggestionSurface
        ) => WarehouseSuggestionApi[]
        surfaceSuggestions: (
            listedSuggestions: WarehouseSuggestionApi[],
            leavingSuggestionIds: string[]
        ) => WarehouseSuggestionApi[]
        savingsSummary: (surfaceSuggestions: WarehouseSuggestionApi[]) => SavingsSummary
        materializeModalSuggestion: (
            suggestions: WarehouseSuggestionApi[] | null,
            materializeModalSuggestionId: string | null
        ) => WarehouseSuggestionApi | null
        acceptConfirmSuggestion: (
            suggestions: WarehouseSuggestionApi[] | null,
            acceptConfirmSuggestionId: string | null
        ) => WarehouseSuggestionApi | null
        materializeDisabledReason: (
            materializeInterval: DataModelingSyncInterval | null,
            refreshDraft: IncrementalConfigDraft,
            incrementalCheckLoading: boolean
        ) => string | null
        materializeIntervalShorterThanSuggested: (
            materializeModalSuggestion: WarehouseSuggestionApi | null,
            materializeInterval: DataModelingSyncInterval | null
        ) => boolean
        stripState: (
            suggestions: WarehouseSuggestionApi[] | null,
            status: WarehouseSuggestionStatusApi | null,
            loadError: boolean,
            featureForbidden: boolean,
            surfaceSuggestions: WarehouseSuggestionApi[],
            hiddenSuggestionIds: string[],
            leavingSuggestionIds: string[]
        ) => StripState
    }
}

export type warehouseSuggestionsLogicType = MakeLogicType<
    warehouseSuggestionsLogicValues,
    warehouseSuggestionsLogicActions,
    WarehouseSuggestionsLogicProps,
    warehouseSuggestionsLogicMeta
>

export const warehouseSuggestionsLogic: LogicWrapper<warehouseSuggestionsLogicType> =
    kea<warehouseSuggestionsLogicType>([
        props({} as WarehouseSuggestionsLogicProps),
        key((props) => props.surface),
        path((key) => ['products', 'warehouseSuggestions', 'warehouseSuggestionsLogic', key]),
        actions({
            acceptSuggestion: (id: string, options?: AcceptWarehouseSuggestionApi) => ({ id, options }),
            confirmMaterialize: true,
            setRefreshDraft: (draft: Partial<IncrementalConfigDraft>) => ({ draft }),
            dismissSuggestion: (id: string, reason: DismissWarehouseSuggestionApi['reason'], note?: string) => ({
                id,
                reason,
                note,
            }),
            setActionInFlight: (id: string, inFlight: boolean) => ({ id, inFlight }),
            hideSuggestion: (id: string) => ({ id }),
            finishHidingSuggestion: (id: string) => ({ id }),
            restoreSuggestion: (id: string) => ({ id }),
            undoDismiss: (id: string) => ({ id }),
            suggestionResumed: (suggestion: WarehouseSuggestionApi) => ({ suggestion }),
            openReview: true,
            closeReview: true,
            openMaterializeModal: (id: string) => ({ id }),
            closeMaterializeModal: true,
            openAcceptConfirm: (id: string) => ({ id }),
            closeAcceptConfirm: true,
            confirmAccept: true,
            acceptSuggestionFailed: (id: string) => ({ id }),
            setKeepMaterialized: (keepMaterialized: boolean) => ({ keepMaterialized }),
            setMaterializeError: (error: string | null) => ({ error }),
            setMaterializeInterval: (interval: DataModelingSyncInterval | null) => ({ interval }),
            suggestionAccepted: (suggestion: WarehouseSuggestionApi) => ({ suggestion }),
            reload: true,
        }),
        loaders(({ values }) => ({
            suggestions: [
                null as WarehouseSuggestionApi[] | null,
                {
                    loadSuggestions: async () =>
                        (await warehouseSuggestionsList(projectId(), { status: 'proposed' })).results,
                },
            ],
            status: [
                null as WarehouseSuggestionStatusApi | null,
                {
                    loadStatus: async () => await warehouseSuggestionsStatusRetrieve(projectId()),
                },
            ],
            incrementalCheck: [
                null as IncrementalEligibilityApi | null,
                {
                    loadIncrementalCheck: async (viewId: string, breakpoint) => {
                        const check = await fetchIncrementalCheck(viewId)
                        breakpoint()
                        return values.materializeModalSuggestion?.subject_id === viewId ? check : null
                    },
                    closeMaterializeModal: () => null,
                },
            ],
        })),
        reducers(() => ({
            suggestions: {
                suggestionResumed: (state: WarehouseSuggestionApi[] | null, { suggestion }) => [
                    ...(state ?? []).filter((existing) => existing.id !== suggestion.id),
                    suggestion,
                ],
            },
            actionsInFlight: [
                {} as Record<string, boolean>,
                {
                    setActionInFlight: (state, { id, inFlight }) => ({ ...state, [id]: inFlight }),
                },
            ],
            leavingSuggestionIds: [
                [] as string[],
                {
                    hideSuggestion: (state, { id }) => (state.includes(id) ? state : [...state, id]),
                    finishHidingSuggestion: (state, { id }) => state.filter((leavingId) => leavingId !== id),
                    restoreSuggestion: (state, { id }) => state.filter((leavingId) => leavingId !== id),
                },
            ],
            hiddenSuggestionIds: [
                [] as string[],
                {
                    finishHidingSuggestion: (state, { id }) => (state.includes(id) ? state : [...state, id]),
                    restoreSuggestion: (state, { id }) => state.filter((hiddenId) => hiddenId !== id),
                },
            ],
            reviewOpen: [
                false,
                {
                    openReview: () => true,
                    closeReview: () => false,
                },
            ],
            materializeModalSuggestionId: [
                null as string | null,
                {
                    openMaterializeModal: (_, { id }) => id,
                    closeMaterializeModal: () => null,
                    hideSuggestion: (state, { id }) => (state === id ? null : state),
                },
            ],
            acceptConfirmSuggestionId: [
                null as string | null,
                {
                    openAcceptConfirm: (_, { id }) => id,
                    closeAcceptConfirm: () => null,
                    hideSuggestion: (state, { id }) => (state === id ? null : state),
                    acceptSuggestionFailed: (state, { id }) => (state === id ? null : state),
                },
            ],
            keepMaterialized: [
                false,
                {
                    setKeepMaterialized: (_, { keepMaterialized }) => keepMaterialized,
                    openAcceptConfirm: () => false,
                    closeAcceptConfirm: () => false,
                },
            ],
            materializeInterval: [
                null as DataModelingSyncInterval | null,
                {
                    setMaterializeInterval: (_, { interval }) => interval,
                    closeMaterializeModal: () => null,
                },
            ],
            refreshDraft: [
                EMPTY_INCREMENTAL_DRAFT as IncrementalConfigDraft,
                {
                    setRefreshDraft: (state, { draft }) => ({ ...state, ...draft }),
                    closeMaterializeModal: () => EMPTY_INCREMENTAL_DRAFT,
                },
            ],
            materializeError: [
                null as string | null,
                {
                    setMaterializeError: (_, { error }) => error,
                    setRefreshDraft: () => null,
                    setMaterializeInterval: () => null,
                    openMaterializeModal: () => null,
                    closeMaterializeModal: () => null,
                },
            ],
            loadError: [
                false,
                {
                    reload: () => false,
                    loadSuggestionsFailure: (_, { errorObject }) => !isForbidden(errorObject),
                    loadStatusFailure: (_, { errorObject }) => !isForbidden(errorObject),
                },
            ],
            featureForbidden: [
                false,
                {
                    reload: () => false,
                    loadSuggestionsFailure: (forbidden, { errorObject }) => forbidden || isForbidden(errorObject),
                    loadStatusFailure: (forbidden, { errorObject }) => forbidden || isForbidden(errorObject),
                },
            ],
        })),
        selectors({
            listedSuggestions: [
                (s, p) => [s.suggestions, s.hiddenSuggestionIds, p.surface],
                (
                    suggestions: WarehouseSuggestionApi[] | null,
                    hiddenIds: string[],
                    surface: SuggestionSurface
                ): WarehouseSuggestionApi[] =>
                    (suggestions ?? [])
                        .filter(
                            (suggestion) =>
                                suggestion.surfaced_at !== null &&
                                !hiddenIds.includes(suggestion.id) &&
                                SURFACE_KINDS[surface].includes(suggestion.kind)
                        )
                        .sort(compareSuggestions),
            ],
            surfaceSuggestions: [
                (s) => [s.listedSuggestions, s.leavingSuggestionIds],
                (listed: WarehouseSuggestionApi[], leavingIds: string[]): WarehouseSuggestionApi[] =>
                    listed.filter((suggestion) => !leavingIds.includes(suggestion.id)),
            ],
            savingsSummary: [
                (s) => [s.surfaceSuggestions],
                (open: WarehouseSuggestionApi[]): SavingsSummary => {
                    const savings = open
                        .map(({ payload }) => monthlySaving(payload))
                        .filter((saving): saving is MonthlySaving => saving !== null)
                    return {
                        views: savings.length,
                        saving: {
                            seconds: sum(savings.map((saving) => saving.seconds)),
                            bytes: sum(savings.map((saving) => saving.bytes)),
                        },
                    }
                },
            ],
            materializeModalSuggestion: [
                (s) => [s.suggestions, s.materializeModalSuggestionId],
                (suggestions: WarehouseSuggestionApi[] | null, id: string | null): WarehouseSuggestionApi | null =>
                    (suggestions ?? []).find((suggestion) => suggestion.id === id) ?? null,
            ],
            acceptConfirmSuggestion: [
                (s) => [s.suggestions, s.acceptConfirmSuggestionId],
                (suggestions: WarehouseSuggestionApi[] | null, id: string | null): WarehouseSuggestionApi | null =>
                    (suggestions ?? []).find((suggestion) => suggestion.id === id) ?? null,
            ],
            materializeDisabledReason: [
                (s) => [s.materializeInterval, s.refreshDraft, s.incrementalCheckLoading],
                (
                    interval: DataModelingSyncInterval | null,
                    draft: IncrementalConfigDraft,
                    checkLoading: boolean
                ): string | null => {
                    if (!interval) {
                        return PICK_INTERVAL_REASON
                    }
                    if (checkLoading) {
                        return CHECKING_INCREMENTAL_REASON
                    }
                    if (draft.enabled && (!draft.incrementalKey || draft.uniqueKey.length === 0)) {
                        return INCOMPLETE_INCREMENTAL_REASON
                    }
                    return null
                },
            ],
            materializeIntervalShorterThanSuggested: [
                (s) => [s.materializeModalSuggestion, s.materializeInterval],
                (suggestion: WarehouseSuggestionApi | null, interval: DataModelingSyncInterval | null): boolean =>
                    !!suggestion &&
                    !!interval &&
                    isMaterializePayload(suggestion.payload) &&
                    INTERVAL_SECONDS[interval] < suggestion.payload.refresh_interval_seconds,
            ],
            stripState: [
                (s) => [
                    s.suggestions,
                    s.status,
                    s.loadError,
                    s.featureForbidden,
                    s.surfaceSuggestions,
                    s.hiddenSuggestionIds,
                    s.leavingSuggestionIds,
                ],
                (
                    suggestions: WarehouseSuggestionApi[] | null,
                    status: WarehouseSuggestionStatusApi | null,
                    loadError: boolean,
                    featureForbidden: boolean,
                    surfaceSuggestions: WarehouseSuggestionApi[],
                    hiddenIds: string[],
                    leavingIds: string[]
                ): StripState => {
                    if (featureForbidden) {
                        return 'hidden'
                    }
                    if (suggestions === null || status === null) {
                        return loadError ? 'error' : 'loading'
                    }
                    if (surfaceSuggestions.length > 0) {
                        return 'active'
                    }
                    if (hiddenIds.length + leavingIds.length > 0) {
                        return 'all_done'
                    }
                    if (!status.enabled || status.refreshed_at === null) {
                        return 'hidden'
                    }
                    if (!status.eligible) {
                        return 'not_eligible'
                    }
                    return status.days_with_data < status.window_days ? 'warming_up' : 'hidden'
                },
            ],
        }),
        listeners(({ actions, values, props, cache, selectors }) => {
            const reportViewedOnce = (): void => {
                if (cache.viewReported || values.stripState !== 'active') {
                    return
                }
                cache.viewReported = true
                posthog.capture('warehouse suggestions viewed', {
                    surface: props.surface,
                    suggestion_count: values.surfaceSuggestions.length,
                })
            }
            const viewAction = (suggestion: WarehouseSuggestionApi): (() => void) | null => {
                const opensModelPage = VIEW_ON_MODEL_PAGE_KINDS.includes(suggestion.kind)
                if (!opensModelPage && !suggestion.created_asset?.certification_id) {
                    return null
                }
                const onViewAccepted = props.onViewAccepted
                if (!onViewAccepted && !opensModelPage) {
                    return null
                }
                return () => {
                    actions.closeReview()
                    if (onViewAccepted) {
                        onViewAccepted(suggestion)
                        return
                    }
                    router.actions.push(subjectUrl(suggestion, 'materialization'))
                }
            }
            return {
                reload: () => {
                    actions.loadSuggestions()
                    actions.loadStatus()
                },
                loadSuggestionsSuccess: () => reportViewedOnce(),
                loadStatusSuccess: () => reportViewedOnce(),
                closeMaterializeModal: (_, __, ___, previousState) => {
                    posthog.capture('warehouse suggestion materialize cancelled', {
                        suggestion_id: selectors.materializeModalSuggestionId(previousState),
                    })
                },
                openAcceptConfirm: ({ id }) => {
                    posthog.capture('warehouse suggestion confirm opened', {
                        suggestion_id: id,
                        kind: values.acceptConfirmSuggestion?.kind,
                    })
                },
                closeAcceptConfirm: (_, __, ___, previousState) => {
                    posthog.capture('warehouse suggestion confirm cancelled', {
                        suggestion_id: selectors.acceptConfirmSuggestionId(previousState),
                    })
                },
                confirmAccept: () => {
                    const suggestion = values.acceptConfirmSuggestion
                    if (!suggestion) {
                        return
                    }
                    const keepMaterialized = suggestion.kind === 'deprecate' && values.keepMaterialized
                    actions.acceptSuggestion(suggestion.id, keepMaterialized ? { keep_materialized: true } : undefined)
                },
                openReview: () => {
                    posthog.capture('warehouse suggestion review opened', {
                        surface: props.surface,
                        suggestion_count: values.surfaceSuggestions.length,
                    })
                },
                openMaterializeModal: ({ id }) => {
                    posthog.capture('warehouse suggestion materialize opened', { suggestion_id: id })
                    const payload = values.suggestions?.find((suggestion) => suggestion.id === id)?.payload
                    if (!payload || !isMaterializePayload(payload)) {
                        actions.setMaterializeInterval(null)
                        return
                    }
                    actions.setMaterializeInterval(intervalForSeconds(payload.refresh_interval_seconds))
                    actions.setRefreshDraft(proposedRefreshDraft(payload))
                    const subjectId = values.suggestions?.find((suggestion) => suggestion.id === id)?.subject_id
                    if (subjectId) {
                        actions.loadIncrementalCheck(subjectId)
                    }
                },
                hideSuggestion: ({ id }) => {
                    cache.disposables.add(() => {
                        const timer = setTimeout(() => actions.finishHidingSuggestion(id), ROW_LEAVE_MS)
                        return () => clearTimeout(timer)
                    }, leaveDisposableKey(id))
                },
                restoreSuggestion: ({ id }) => {
                    cache.disposables.dispose(leaveDisposableKey(id))
                },
                suggestionAccepted: ({ suggestion }) => {
                    const view = viewAction(suggestion)
                    lemonToast.success(ACCEPTED_MESSAGES[suggestion.kind]?.(suggestion) ?? 'Accepted.', {
                        toastId: `warehouse-suggestion-accepted-${suggestion.id}`,
                        button: view ? { label: 'View', action: view } : undefined,
                    })
                },
                loadIncrementalCheckSuccess: ({ incrementalCheck }) => {
                    if (!incrementalCheck) {
                        return
                    }
                    if (!incrementalCheck.eligible || incrementalCheck.key_candidates.length === 0) {
                        actions.setRefreshDraft({ enabled: false })
                        return
                    }
                    if (values.refreshDraft.incrementalKey) {
                        return
                    }
                    actions.setRefreshDraft({ incrementalKey: incrementalCheck.key_candidates[0] ?? null })
                },
                confirmMaterialize: () => {
                    const suggestion = values.materializeModalSuggestion
                    const interval = values.materializeInterval
                    if (
                        !suggestion ||
                        !interval ||
                        values.materializeDisabledReason ||
                        !isMaterializePayload(suggestion.payload)
                    ) {
                        return
                    }
                    actions.acceptSuggestion(suggestion.id, {
                        refresh_interval_seconds: INTERVAL_SECONDS[interval],
                        ...changedRefreshOptions(suggestion.payload, values.refreshDraft),
                    })
                },
                acceptSuggestion: async ({ id, options }) => {
                    if (values.actionsInFlight[id]) {
                        return
                    }
                    actions.setActionInFlight(id, true)
                    try {
                        const accepted = await warehouseSuggestionsAcceptCreate(projectId(), id, options)
                        actions.hideSuggestion(id)
                        actions.suggestionAccepted(accepted)
                        props.onAccepted?.(accepted)
                    } catch (error) {
                        if (error instanceof ApiError && error.attr && ACCEPT_OPTION_FIELDS.has(error.attr)) {
                            actions.setMaterializeError(error.detail)
                        } else {
                            reportAcceptFailure(error)
                            actions.acceptSuggestionFailed(id)
                            if (isStale(error)) {
                                actions.loadSuggestions()
                            }
                        }
                    } finally {
                        actions.setActionInFlight(id, false)
                    }
                },
                dismissSuggestion: async ({ id, reason, note }) => {
                    if (values.actionsInFlight[id]) {
                        return
                    }
                    const kind = values.suggestions?.find((suggestion) => suggestion.id === id)?.kind ?? ''
                    const project = projectId()
                    actions.setActionInFlight(id, true)
                    actions.hideSuggestion(id)
                    try {
                        await warehouseSuggestionsDismissCreate(project, id, { reason, note })
                        lemonToast.success(dismissedMessage(reason, kind), {
                            toastId: `warehouse-suggestion-dismissed-${id}`,
                            button: {
                                label: 'Undo',
                                action: () => void resumeDismissedSuggestion(props.surface, project, id),
                            },
                        })
                    } catch (error) {
                        actions.restoreSuggestion(id)
                        reportFailure(error, 'Could not dismiss the suggestion.')
                        if (isStale(error)) {
                            actions.loadSuggestions()
                        }
                    } finally {
                        actions.setActionInFlight(id, false)
                    }
                },
                undoDismiss: async ({ id }) => {
                    await resumeDismissedSuggestion(props.surface, projectId(), id)
                },
            }
        }),
        afterMount(({ actions }) => {
            actions.reload()
        }),
    ])

async function resumeDismissedSuggestion(surface: SuggestionSurface, project: string, id: string): Promise<void> {
    const mounted = (): ReturnType<typeof warehouseSuggestionsLogic.build> | null =>
        warehouseSuggestionsLogic.findMounted({ surface })
    if (mounted()?.values.actionsInFlight[id]) {
        return
    }
    mounted()?.actions.setActionInFlight(id, true)
    try {
        const resumed = await warehouseSuggestionsResumeCreate(project, id)
        mounted()?.actions.suggestionResumed(resumed)
        mounted()?.actions.restoreSuggestion(id)
    } catch (error) {
        reportFailure(error, 'Could not bring the suggestion back.')
        if (isStale(error)) {
            mounted()?.actions.loadSuggestions()
        }
    } finally {
        mounted()?.actions.setActionInFlight(id, false)
    }
}

function isForbidden(error: unknown): boolean {
    return error instanceof ApiError && error.status === FORBIDDEN_STATUS
}

function isConflict(error: unknown): boolean {
    return error instanceof ApiError && error.status === CONFLICT_STATUS
}

function isNotFound(error: unknown): boolean {
    return error instanceof ApiError && error.status === NOT_FOUND_STATUS
}

function isStale(error: unknown): boolean {
    return isConflict(error) || isNotFound(error)
}

function reportAcceptFailure(error: unknown): void {
    if (isConflict(error) && error instanceof ApiError && error.detail) {
        lemonToast.error(error.detail)
        return
    }
    reportFailure(error, 'Could not accept the suggestion.')
}

function reportFailure(error: unknown, fallback: string): void {
    if (isConflict(error)) {
        lemonToast.error('Someone already decided this suggestion. The list is up to date now.')
        return
    }
    if (isNotFound(error)) {
        lemonToast.error('This suggestion is gone, or its view or table was deleted. The list is up to date now.')
        return
    }
    lemonToast.error((error instanceof ApiError && error.detail) || fallback)
}
