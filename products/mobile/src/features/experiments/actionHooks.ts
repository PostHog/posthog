import { type QueryClient, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { create } from 'zustand'
import { ApiError } from '@/api/client'
import {
    approvalChangeRequestId,
    type ExperimentApi,
    type ExperimentConclusionApi,
    experimentKeys,
} from '@/api/experiments'
import type { ProjectScope } from '@/api/reports'
import { coversScope, EXPERIMENTS_SCOPES, missingScope } from '@/api/scopeErrors'
import { addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { getSessionTokens } from '@/auth/tokens'
import { useDataMode } from '@/demo/demoMode'
import { reportScopeError } from '@/features/views/useViewsAccess'
import { track } from '@/lib/analytics'
import { type AsyncAction, useAsyncAction } from '@/lib/useAsyncAction'

import { experimentStatusOf, isLiveStatus } from './experimentModel'
import { type CleanupTargetState, type FinishPreset, type FinishRequest, finishToast } from './finishModel'
import { useExperimentsContext } from './hooks'

/** The action sheets the bar and the More menu open. Only one is open at a time. */
export type ExperimentSheet = 'ship' | 'end' | 'launch' | 'pause' | 'resume' | 'edit_conclusion' | 'archive'

export interface ExperimentActionsController {
    sheet: ExperimentSheet | null
    open: (sheet: ExperimentSheet) => void
    close: () => void
}

/**
 * Which action sheet is open. The detail screen holds it, so the bar and the More menu open the same sheets:
 * `<ExperimentActionBar actions={controller} />` and `experimentMenuItems(experiment, { onOpenSheet: controller.open })`.
 */
export function useExperimentActions(): ExperimentActionsController {
    const [sheet, setSheet] = useState<ExperimentSheet | null>(null)
    const close = useCallback(() => setSheet(null), [])
    return useMemo(() => ({ sheet, open: setSheet, close }), [sheet, close])
}

/**
 * A refusal for a missing experiments scope shows the sign-in state. One for another scope, such as `task:write` on a
 * cleanup PR, stays an error in the sheet: signing in again would not change the experiments screens.
 */
function reportActionError(error: unknown): void {
    const scope = missingScope(error)
    if (scope && (EXPERIMENTS_SCOPES as readonly string[]).includes(scope)) {
        reportScopeError(error, 'experiments')
    }
}

/** Stores the server's experiment on the detail and refetches the lists, where the row may change segment. */
function applyExperiment(queryClient: QueryClient, scope: ProjectScope | null, experiment: ExperimentApi): void {
    queryClient.setQueryData<ExperimentApi>(experimentKeys.detail(scope, experiment.id), experiment)
    void queryClient.invalidateQueries({ queryKey: experimentKeys.lists(scope) })
}

/** Sets the change on the detail at once. Returns the experiment to put back when the server refuses. */
async function patchDetail(
    queryClient: QueryClient,
    scope: ProjectScope | null,
    id: string,
    patch: (experiment: ExperimentApi) => ExperimentApi
): Promise<ExperimentApi | undefined> {
    const key = experimentKeys.detail(scope, id)
    // A refresh that lands after the optimistic patch would put the old values back.
    await queryClient.cancelQueries({ queryKey: key })
    const previous = queryClient.getQueryData<ExperimentApi>(key)
    if (previous) {
        queryClient.setQueryData<ExperimentApi>(key, patch(previous))
    }
    return previous
}

function restoreDetail(
    queryClient: QueryClient,
    scope: ProjectScope | null,
    id: string,
    previous: ExperimentApi | undefined
): void {
    if (previous) {
        queryClient.setQueryData<ExperimentApi>(experimentKeys.detail(scope, id), previous)
    }
}

function withFlagActive(experiment: ExperimentApi, active: boolean): ExperimentApi {
    return experiment.feature_flag
        ? { ...experiment, feature_flag: { ...experiment.feature_flag, active } }
        : experiment
}

// Pending approvals. The API has no read for a flag's open change requests within the app's scopes, so the screen
// remembers the 409 for the rest of the session.

export interface PendingApproval {
    changeRequestId: string
    variant: string
    /** Epoch ms of the 409. */
    sentAt: number
    /** `change_request_pending`: a request for this change already waited, so nothing new was sent. */
    alreadyPending: boolean
}

interface PendingApprovalsState {
    byExperiment: Record<string, PendingApproval>
}

const usePendingApprovals = create<PendingApprovalsState>()(() => ({ byExperiment: {} }))

addSessionEndTask(() => usePendingApprovals.setState({ byExperiment: {} }))

function setPendingApproval(id: string, approval: PendingApproval | null): void {
    usePendingApprovals.setState((state) => {
        const next = { ...state.byExperiment }
        if (approval) {
            next[id] = approval
        } else {
            delete next[id]
        }
        return { byExperiment: next }
    })
}

/** The ship request waiting for an approval, while the experiment is still live. */
export function usePendingApproval(experiment: ExperimentApi): PendingApproval | null {
    const approval = usePendingApprovals((state) => state.byExperiment[String(experiment.id)] ?? null)
    return approval && isLiveStatus(experimentStatusOf(experiment)) ? approval : null
}

// Analytics: properties are enums, ids and counts only.

type FinishOutcome = 'done' | 'needs_approval' | 'failed'

function trackFinished(request: FinishRequest, preset: FinishPreset, outcome: FinishOutcome): void {
    track('mobile_experiment_finished', {
        preset,
        shipped: request.kind === 'ship',
        release: request.kind === 'ship' ? (request.body.release_to_everyone ? 'everyone' : 'population') : 'none',
        conclusion: request.body.conclusion ?? 'none',
        cleanup_pr: request.body.open_cleanup_pr === true,
        outcome,
    })
}

function trackLaunched(): void {
    track('mobile_experiment_launched')
}

function trackPauseResume(mode: 'pause' | 'resume'): void {
    track(mode === 'pause' ? 'mobile_experiment_paused' : 'mobile_experiment_resumed')
}

function trackArchived(): void {
    track('mobile_experiment_archived')
}

function trackConclusionEdited(props: {
    from: ExperimentConclusionApi | null
    to: ExperimentConclusionApi
    hasComment: boolean
}): void {
    track('mobile_experiment_conclusion_edited', {
        from: props.from ?? 'none',
        to: props.to,
        has_comment: props.hasComment,
    })
}

/**
 * A write the flag's approval gate held (409 with `change_request_id`): a change request waits for a reviewer and
 * nothing changed. Launch rejects with it, so every launch sheet, on the detail and on the list, shows the request
 * instead of an error.
 */
export class ChangeRequestPendingError extends Error {
    readonly changeRequestId: string
    /** `change_request_pending`: a request for this change already waited, so the server sent no new one. */
    readonly alreadyPending: boolean

    constructor(changeRequestId: string, alreadyPending: boolean) {
        super(alreadyPending ? 'A change request is already waiting for approval.' : 'A change request was sent.')
        this.name = 'ChangeRequestPendingError'
        this.changeRequestId = changeRequestId
        this.alreadyPending = alreadyPending
    }
}

function changeRequestOf(error: unknown): ChangeRequestPendingError | null {
    const changeRequestId = approvalChangeRequestId(error)
    if (!changeRequestId) {
        return null
    }
    return new ChangeRequestPendingError(
        changeRequestId,
        error instanceof ApiError && error.code === 'change_request_pending'
    )
}

// Actions. Each one runs through `useAsyncAction`, so a second tap while one is in flight does nothing.

export function useLaunchAction(experimentId: string): AsyncAction<[onDone: () => void]> {
    const queryClient = useQueryClient()
    const { scope, source } = useExperimentsContext()
    return useAsyncAction(async (onDone: () => void) => {
        try {
            // No optimistic patch: the sheet shows the wait, and a refused launch leaves nothing to undo.
            const experiment = await source.launchExperiment(experimentId)
            applyExperiment(queryClient, scope, experiment)
            void queryClient.invalidateQueries({ queryKey: experimentKeys.experimentAll(scope, experimentId) })
            trackLaunched()
            onDone()
        } catch (error) {
            // Launch turns the flag on through the approval gate, so a policy can hold it.
            const pending = changeRequestOf(error)
            if (pending) {
                throw pending
            }
            reportActionError(error)
            throw error
        }
    })
}

export interface FinishRun {
    request: FinishRequest
    preset: FinishPreset
    onFinished: (toast: string) => void
    onNeedsApproval: (approval: PendingApproval) => void
}

/**
 * Ship (`POST ship_variant/`) or end (`POST end/`). No optimistic patch and no Undo: shipping rewrites the flag, and a
 * 409 means nothing changed yet.
 */
export function useFinishAction(experimentId: string): AsyncAction<[FinishRun]> {
    const queryClient = useQueryClient()
    const { scope, source } = useExperimentsContext()
    return useAsyncAction(async ({ request, preset, onFinished, onNeedsApproval }: FinishRun) => {
        try {
            let experiment: ExperimentApi
            if (request.kind === 'ship') {
                const result = await source.shipVariant(experimentId, request.body)
                if (result.status === 'needs_approval') {
                    const approval: PendingApproval = {
                        changeRequestId: result.changeRequestId,
                        variant: request.variant,
                        sentAt: Date.now(),
                        alreadyPending: result.code === 'change_request_pending',
                    }
                    setPendingApproval(experimentId, approval)
                    trackFinished(request, preset, 'needs_approval')
                    onNeedsApproval(approval)
                    return
                }
                experiment = result.experiment
            } else {
                experiment = await source.endExperiment(experimentId, request.body)
            }
            applyExperiment(queryClient, scope, experiment)
            setPendingApproval(experimentId, null)
            trackFinished(request, preset, 'done')
            const cleanupStarted = request.body.open_cleanup_pr === true && Boolean(experiment.flag_cleanup_task_id)
            onFinished(finishToast(request, cleanupStarted))
        } catch (error) {
            trackFinished(request, preset, 'failed')
            reportActionError(error)
            throw error
        }
    })
}

export type PauseResumeOutcome = 'done' | 'needs_approval' | 'already_waiting'

/**
 * Pause turns the flag off and resume turns it on, both through the flag's approval gate. A 409 means a change request
 * now waits for a reviewer and the flag did not change.
 */
export function usePauseResumeAction(
    experimentId: string
): AsyncAction<['pause' | 'resume', (outcome: PauseResumeOutcome) => void]> {
    const queryClient = useQueryClient()
    const { scope, source } = useExperimentsContext()
    return useAsyncAction(async (mode: 'pause' | 'resume', onDone: (outcome: PauseResumeOutcome) => void) => {
        const pause = mode === 'pause'
        const previous = await patchDetail(queryClient, scope, experimentId, (experiment) =>
            withFlagActive({ ...experiment, status: pause ? 'paused' : 'running' }, !pause)
        )
        try {
            const experiment = pause
                ? await source.pauseExperiment(experimentId)
                : await source.resumeExperiment(experimentId)
            applyExperiment(queryClient, scope, experiment)
            trackPauseResume(mode)
            onDone('done')
        } catch (error) {
            restoreDetail(queryClient, scope, experimentId, previous)
            const pending = changeRequestOf(error)
            if (pending) {
                onDone(pending.alreadyPending ? 'already_waiting' : 'needs_approval')
                return
            }
            reportActionError(error)
            throw error
        }
    })
}

/** Archives without touching the flag: `disable_feature_flag` needs `feature_flag:write`. */
export function useArchiveAction(experimentId: string): AsyncAction<[() => void]> {
    const queryClient = useQueryClient()
    const { scope, source } = useExperimentsContext()
    return useAsyncAction(async (onDone: () => void) => {
        const previous = await patchDetail(queryClient, scope, experimentId, (experiment) => ({
            ...experiment,
            archived: true,
        }))
        try {
            const experiment = await source.archiveExperiment(experimentId)
            applyExperiment(queryClient, scope, experiment)
            trackArchived()
            onDone()
        } catch (error) {
            restoreDetail(queryClient, scope, experimentId, previous)
            reportActionError(error)
            throw error
        }
    })
}

export interface ConclusionPatch {
    conclusion: ExperimentConclusionApi
    comment: string
}

/** `PATCH experiments/{id}/` with the conclusion and its comment. The flag does not change. */
export function useEditConclusionAction(experimentId: string): AsyncAction<[ConclusionPatch, () => void]> {
    const queryClient = useQueryClient()
    const { scope, source } = useExperimentsContext()
    return useAsyncAction(async ({ conclusion, comment }: ConclusionPatch, onDone: () => void) => {
        const text = comment.trim()
        const patch = { conclusion, conclusion_comment: text || null }
        const previous = await patchDetail(queryClient, scope, experimentId, (experiment) => ({
            ...experiment,
            ...patch,
        }))
        try {
            const experiment = await source.updateExperiment(experimentId, patch)
            applyExperiment(queryClient, scope, experiment)
            trackConclusionEdited({ from: previous?.conclusion ?? null, to: conclusion, hasComment: text.length > 0 })
            onDone()
        } catch (error) {
            restoreDetail(queryClient, scope, experimentId, previous)
            reportActionError(error)
            throw error
        }
    })
}

/** True unless an OAuth grant is known to lack `task:write`, which `open_cleanup_pr` needs. */
function useTaskWriteGranted(): boolean {
    const mode = useDataMode()
    const method = useAuthStore((state) => state.method)
    // Changes on every sign-in, so the grant below is read again.
    useAuthStore((state) => state.status)
    if (mode !== 'live' || method !== 'oauth') {
        return true
    }
    const granted = getSessionTokens()?.grantedScopes ?? null
    return granted === null || coversScope(granted, 'task:write')
}

export interface CleanupTarget {
    state: CleanupTargetState
    retry: () => void
}

/**
 * The repository a cleanup PR would open in (`GET flag_cleanup_target/`, `experiment:read`). Like the web, it loads
 * when the finish sheet opens, not with the screen, because most visits never open it.
 */
export function useCleanupTarget(experimentId: string, enabled: boolean): CleanupTarget {
    const { scope, ready, source } = useExperimentsContext()
    const available = useTaskWriteGranted()
    const query = useQuery({
        queryKey: experimentKeys.cleanupTarget(scope, experimentId),
        queryFn: ({ signal }) => source.fetchFlagCleanupTarget(experimentId, signal),
        enabled: enabled && available && ready,
        staleTime: 60_000,
        retry: false,
    })
    const { refetch } = query
    const retry = useCallback((): void => {
        void refetch()
    }, [refetch])
    let state: CleanupTargetState
    if (!available) {
        state = { status: 'unavailable' }
    } else if (query.data) {
        state = { status: 'ready', target: query.data }
    } else {
        state = query.isError && !query.isFetching ? { status: 'error' } : { status: 'loading' }
    }
    return { state, retry }
}
