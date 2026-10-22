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
import { urls } from 'scenes/urls'

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
import { SavingsSummary, isMaterializePayload, savesTime } from './suggestionCopy'

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
    models: ['materialize'],
    catalog: ['certify', 'deprecate'],
}
const CONFLICT_STATUS = 409
const ACCEPTED_MESSAGES: Record<string, (name: string) => string> = {
    materialize: (name) => `Materializing ${name}. The first refresh is running.`,
    certify: (name) => `Certified ${name}.`,
    deprecate: (name) => `Marked ${name} as deprecated.`,
}
const ACCEPT_OPTION_FIELDS = new Set([
    'refresh_interval_seconds',
    'refresh_mode',
    'incremental_key',
    'unique_key',
    'lookback_seconds',
])
const DISMISSED_MESSAGES: Record<DismissWarehouseSuggestionApi['reason'], string> = {
    not_useful: 'Dismissed. Not suggested again.',
    not_now: 'Dismissed. Suggested again if reads grow.',
    other: 'Dismissed. Not suggested again.',
}

function suggestionWorth(suggestion: WarehouseSuggestionApi): [number, number] {
    const { payload } = suggestion
    if (!isMaterializePayload(payload)) {
        return [KIND_ORDER[suggestion.kind] ?? 0, 0]
    }
    return savesTime(payload) ? [0, -payload.saves_seconds_per_month] : [1, -payload.saves_bytes_per_month]
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
    actionsInFlight: Record<string, boolean>
    hiddenSuggestionIds: string[]
    incrementalCheck: IncrementalEligibilityApi | null
    incrementalCheckLoading: boolean
    leavingSuggestionIds: string[]
    listedSuggestions: WarehouseSuggestionApi[]
    loadError: boolean
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
        materializeIntervalShorterThanSuggested: (
            materializeModalSuggestion: WarehouseSuggestionApi | null,
            materializeInterval: DataModelingSyncInterval | null
        ) => boolean
        stripState: (
            suggestions: WarehouseSuggestionApi[] | null,
            status: WarehouseSuggestionStatusApi | null,
            loadError: boolean,
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
            setMaterializeError: (error: string | null) => ({ error }),
            setMaterializeInterval: (interval: DataModelingSyncInterval | null) => ({ interval }),
            suggestionAccepted: (suggestion: WarehouseSuggestionApi) => ({ suggestion }),
            reload: true,
        }),
        loaders({
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
                    loadIncrementalCheck: async (viewId: string) => {
                        try {
                            const view = await warehouseSavedQueriesRetrieve(projectId(), viewId)
                            return await warehouseSavedQueriesCheckIncrementalCreate(projectId(), {
                                query: view.query.query,
                            })
                        } catch {
                            return null
                        }
                    },
                    closeMaterializeModal: () => null,
                },
            ],
        }),
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
                    loadSuggestionsFailure: () => true,
                    loadStatusFailure: () => true,
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
                    const payloads = open.map(({ payload }) => payload).filter(isMaterializePayload)
                    const timeSavers = payloads.filter(savesTime)
                    const bytesSavers = payloads.filter((payload) => !savesTime(payload))
                    return {
                        timeViews: timeSavers.length,
                        savedSeconds: sum(timeSavers.map((payload) => payload.saves_seconds_per_month)),
                        bytesViews: bytesSavers.length,
                        savedBytes: sum(bytesSavers.map((payload) => payload.saves_bytes_per_month)),
                    }
                },
            ],
            materializeModalSuggestion: [
                (s) => [s.suggestions, s.materializeModalSuggestionId],
                (suggestions: WarehouseSuggestionApi[] | null, id: string | null): WarehouseSuggestionApi | null =>
                    (suggestions ?? []).find((suggestion) => suggestion.id === id) ?? null,
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
                    s.surfaceSuggestions,
                    s.hiddenSuggestionIds,
                    s.leavingSuggestionIds,
                ],
                (
                    suggestions: WarehouseSuggestionApi[] | null,
                    status: WarehouseSuggestionStatusApi | null,
                    loadError: boolean,
                    surfaceSuggestions: WarehouseSuggestionApi[],
                    hiddenIds: string[],
                    leavingIds: string[]
                ): StripState => {
                    if (loadError) {
                        return 'error'
                    }
                    if (suggestions === null || status === null) {
                        return 'loading'
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
                if (suggestion.kind !== 'materialize' && !suggestion.created_asset?.certification_id) {
                    return null
                }
                const onViewAccepted = props.onViewAccepted
                if (!onViewAccepted && suggestion.kind !== 'materialize') {
                    return null
                }
                return () => {
                    actions.closeReview()
                    if (onViewAccepted) {
                        onViewAccepted(suggestion)
                        return
                    }
                    router.actions.push(urls.sqlEditor({ view_id: suggestion.subject_id }))
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
                    lemonToast.success(
                        ACCEPTED_MESSAGES[suggestion.kind]?.(suggestion.payload.subject_name) ?? 'Accepted.',
                        {
                            toastId: `warehouse-suggestion-accepted-${suggestion.id}`,
                            button: view ? { label: 'View', action: view } : undefined,
                        }
                    )
                },
                loadIncrementalCheckSuccess: ({ incrementalCheck }) => {
                    if (!incrementalCheck || values.refreshDraft.incrementalKey) {
                        return
                    }
                    actions.setRefreshDraft({ incrementalKey: incrementalCheck.key_candidates[0] ?? null })
                },
                confirmMaterialize: () => {
                    const suggestion = values.materializeModalSuggestion
                    const interval = values.materializeInterval
                    if (!suggestion || !interval || !isMaterializePayload(suggestion.payload)) {
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
                            reportFailure(error, 'Could not accept the suggestion.')
                            if (isConflict(error)) {
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
                    actions.setActionInFlight(id, true)
                    actions.hideSuggestion(id)
                    try {
                        await warehouseSuggestionsDismissCreate(projectId(), id, { reason, note })
                        lemonToast.success(DISMISSED_MESSAGES[reason], {
                            toastId: `warehouse-suggestion-dismissed-${id}`,
                            button: { label: 'Undo', action: () => actions.undoDismiss(id) },
                        })
                    } catch (error) {
                        actions.restoreSuggestion(id)
                        reportFailure(error, 'Could not dismiss the suggestion.')
                        if (isConflict(error)) {
                            actions.loadSuggestions()
                        }
                    } finally {
                        actions.setActionInFlight(id, false)
                    }
                },
                undoDismiss: async ({ id }) => {
                    if (values.actionsInFlight[id]) {
                        return
                    }
                    actions.setActionInFlight(id, true)
                    try {
                        const resumed = await warehouseSuggestionsResumeCreate(projectId(), id)
                        actions.suggestionResumed(resumed)
                        actions.restoreSuggestion(id)
                    } catch (error) {
                        reportFailure(error, 'Could not bring the suggestion back.')
                        if (isConflict(error)) {
                            actions.loadSuggestions()
                        }
                    } finally {
                        actions.setActionInFlight(id, false)
                    }
                },
            }
        }),
        afterMount(({ actions }) => {
            actions.reload()
        }),
    ])

function isConflict(error: unknown): boolean {
    return error instanceof ApiError && error.status === CONFLICT_STATUS
}

function reportFailure(error: unknown, fallback: string): void {
    if (isConflict(error)) {
        lemonToast.error('Someone already decided this suggestion. The list is up to date now.')
        return
    }
    lemonToast.error((error instanceof ApiError && error.detail) || fallback)
}
