import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { ApiError } from 'lib/api'
import { notebookNodeStalenessLogic } from 'scenes/notebooks/Notebook/notebookNodeStalenessLogic'
import { notebookOperationsLogic } from 'scenes/notebooks/Notebook/notebookOperationsLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    notebooksWidgetCancel,
    notebooksWidgetFrame,
    notebooksWidgetGenerate,
    notebooksWidgetRevert,
    notebooksWidgetSaveSource,
    notebooksWidgetSource,
    notebooksWidgetStatus,
    notebooksWidgetVersions,
    notebooksSqlV2StateRetrieve,
} from 'products/notebooks/frontend/generated/api'
import type {
    NotebookCellStateApi,
    WidgetFrameApi,
    WidgetSourceResponseApi,
    WidgetStatusApi,
    WidgetVersionApi,
} from 'products/notebooks/frontend/generated/api.schemas'

import { DEFAULT_WIDGET_MODEL, WIDGET_MODEL_INFO, isWidgetModel, type WidgetModel } from './widgetModels'

const STATUS_POLL_INTERVAL_MS = 2_000
const STATUS_POLL_MAX_INTERVAL_MS = 30_000
const VERSION_PAGE_SIZE = 25
const DATAFRAME_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/

export type WidgetGenerationOperation = 'initial' | 'regenerate' | 'improve'
export type WidgetGenerationModalOperation = Exclude<WidgetGenerationOperation, 'initial'> | null

export type WidgetWorkingStatus = {
    detail: string
    isOverEstimate: boolean
    label: string
    timing: string
}

export type NotebookNodeGeneratedWidgetLogicProps = {
    notebookShortId: string
    nodeId: string
    prompt: string
    model: WidgetModel
    isEditable: boolean
    persistNotebook: () => Promise<void>
}

type WidgetDataRunPlan = {
    missingFrameName: string | null
    nodeIds: string[]
}

function buildWidgetDataRunPlan(cells: NotebookCellStateApi[], frameNames: string[]): WidgetDataRunPlan {
    const ownerByFrame = new Map<string, string>()
    for (const cellType of ['sql', 'python']) {
        for (const cell of cells) {
            if (
                cell.cell_type === cellType &&
                DATAFRAME_NAME.test(cell.dataframe_name) &&
                !ownerByFrame.has(cell.dataframe_name)
            ) {
                ownerByFrame.set(cell.dataframe_name, cell.node_id)
            }
        }
    }

    const sourceNodeIds = new Set<string>()
    for (const frameName of frameNames) {
        const ownerNodeId = ownerByFrame.get(frameName)
        if (!ownerNodeId) {
            return { missingFrameName: frameName, nodeIds: [] }
        }
        sourceNodeIds.add(ownerNodeId)
    }

    const cellsByNodeId = new Map(cells.map((cell) => [cell.node_id, cell]))
    const requiredNodeIds = new Set<string>()
    const addUpstreamNodes = (nodeId: string): void => {
        if (requiredNodeIds.has(nodeId)) {
            return
        }
        requiredNodeIds.add(nodeId)
        cellsByNodeId.get(nodeId)?.depends_on.forEach(addUpstreamNodes)
    }
    sourceNodeIds.forEach(addUpstreamNodes)

    const nodeIdsToRun = new Set(sourceNodeIds)
    for (const cell of cells) {
        if (requiredNodeIds.has(cell.node_id) && cell.status !== 'done') {
            nodeIdsToRun.add(cell.node_id)
        }
    }
    let addedDependent = true
    while (addedDependent) {
        addedDependent = false
        for (const cell of cells) {
            if (
                requiredNodeIds.has(cell.node_id) &&
                !nodeIdsToRun.has(cell.node_id) &&
                cell.depends_on.some((nodeId) => nodeIdsToRun.has(nodeId))
            ) {
                nodeIdsToRun.add(cell.node_id)
                addedDependent = true
            }
        }
    }

    return {
        missingFrameName: null,
        nodeIds: cells
            .filter(
                (cell) =>
                    nodeIdsToRun.has(cell.node_id) &&
                    (cell.cell_type === 'sql' || cell.cell_type === 'python') &&
                    requiredNodeIds.has(cell.node_id)
            )
            .map((cell) => cell.node_id),
    }
}

export interface notebookNodeGeneratedWidgetLogicValues {
    activeDataRunRequestId: string | null
    activeGenerationModel: WidgetModel
    activeFrameNames: string[]
    artifactUnavailable: boolean
    cancellationInFlight: boolean
    currentTeamId: number | null
    elapsedSeconds: number
    frameRevision: number
    dataRunInFlight: boolean
    generationDraftLoading: boolean
    generationDraftModel: WidgetModel
    generationDraftPrompt: string
    generationError: string | null
    generationModalOperation: WidgetGenerationModalOperation
    generationRequestLoading: boolean
    isWorking: boolean
    isCellChainRunning: boolean
    isNotebookBusy: boolean
    restoreInFlight: boolean
    runtimeError: string | null
    selectedVersion: WidgetVersionApi | null
    selectedVersionId: string | null
    sourceDraft: string
    sourceError: string | null
    sourceLoading: boolean
    sourceModalOpen: boolean
    sourceNote: string
    sourceSaving: boolean
    status: WidgetStatusApi | null
    statusLoadError: string | null
    statusLoading: boolean
    versions: WidgetVersionApi[]
    versionsCount: number
    versionsError: string | null
    versionsLoading: boolean
    versionsNextOffset: number | null
    workingStatus: WidgetWorkingStatus | null
}

export interface notebookNodeGeneratedWidgetLogicActions {
    artifactAvailable: () => { value: true }
    artifactRefreshReady: () => { value: true }
    artifactUnavailable: () => { value: true }
    cancelGeneration: () => { value: true }
    cancellationFailed: (error: string) => { error: string }
    cancellationStarted: () => { value: true }
    cellChainFinished: (
        requestId: string,
        success: boolean
    ) => {
        requestId: string
        success: boolean
    }
    closeGenerationModal: () => { value: true }
    closeSourceEditor: () => { value: true }
    generateWidget: (
        prompt: string,
        model: WidgetModel,
        operation: WidgetGenerationOperation
    ) => { prompt: string; model: WidgetModel; operation: WidgetGenerationOperation }
    generationCanceled: () => { value: true }
    generationFailed: (error: string) => { error: string }
    generationRequestFinished: () => { value: true }
    generationRequestStarted: () => { value: true }
    dataRunFinished: (success: boolean, error: string | null) => { success: boolean; error: string | null }
    dataRunStarted: (requestId: string) => { requestId: string }
    loadMoreVersions: () => { value: true }
    loadStatus: () => { value: true }
    loadVersions: (reset: boolean) => { reset: boolean }
    openGenerationModal: (operation: Exclude<WidgetGenerationOperation, 'initial'>) => {
        operation: 'regenerate' | 'improve'
    }
    openSourceEditor: () => { value: true }
    refreshData: () => { value: true }
    runCellChain: (nodeIds: string[], requestId: string) => { nodeIds: string[]; requestId: string }
    runWidget: () => { value: true }
    restoreFailed: (error: string) => { error: string }
    restoreSelectedVersion: () => { value: true }
    restoreStarted: () => { value: true }
    saveSource: () => { value: true }
    selectVersion: (versionId: string) => { versionId: string }
    setGenerationDraftLoading: (loading: boolean) => { loading: boolean }
    setGenerationDraftModel: (model: WidgetModel) => { model: WidgetModel }
    setGenerationDraftPrompt: (prompt: string) => { prompt: string }
    setRuntimeError: (error: string | null) => { error: string | null }
    setSourceDraft: (source: string) => { source: string }
    setSourceNote: (note: string) => { note: string }
    sourceFailed: (error: string) => { error: string }
    sourceLoadStarted: () => { value: true }
    sourceReceived: (source: WidgetSourceResponseApi) => { source: WidgetSourceResponseApi }
    sourceSaveStarted: () => { value: true }
    sourceSaved: () => { value: true }
    statusFailed: (error: string) => { error: string }
    statusReceived: (status: WidgetStatusApi) => { status: WidgetStatusApi }
    tickElapsed: (elapsedSeconds: number) => { elapsedSeconds: number }
    versionsFailed: (error: string) => { error: string }
    versionsReceived: (
        versions: WidgetVersionApi[],
        count: number,
        nextOffset: number | null,
        reset: boolean
    ) => { versions: WidgetVersionApi[]; count: number; nextOffset: number | null; reset: boolean }
}

export interface notebookNodeGeneratedWidgetLogicMeta {
    key: string
}

export type notebookNodeGeneratedWidgetLogicType = MakeLogicType<
    notebookNodeGeneratedWidgetLogicValues,
    notebookNodeGeneratedWidgetLogicActions,
    NotebookNodeGeneratedWidgetLogicProps,
    notebookNodeGeneratedWidgetLogicMeta
>

function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        const response = error.data as { detail?: unknown } | undefined
        if (typeof response?.detail === 'string') {
            return response.detail
        }
    }
    return error instanceof Error ? error.message : 'The widget request failed.'
}

function isMissingNodeError(error: unknown): boolean {
    if (error instanceof ApiError) {
        const response = error.data as { code?: unknown } | undefined
        return error.code === 'node_not_found' || response?.code === 'node_not_found'
    }
    return false
}

function shouldPoll(status: WidgetStatusApi | null): boolean {
    return (
        Boolean(status?.active_job) ||
        status?.lifecycle_status === 'generating' ||
        status?.lifecycle_status === 'building'
    )
}

export function formatWidgetElapsed(elapsedSeconds: number): string {
    const minutes = Math.floor(elapsedSeconds / 60)
    const seconds = elapsedSeconds % 60
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export function getWidgetWorkingStatus({
    elapsedSeconds,
    hasVersions,
    model,
    phase,
}: {
    elapsedSeconds: number
    hasVersions: boolean
    model: WidgetModel
    phase: string
}): WidgetWorkingStatus {
    if (phase === 'queued') {
        return {
            detail: 'Waiting for generation capacity. You can leave this page and come back later.',
            isOverEstimate: false,
            label: hasVersions ? 'Queued to regenerate widget…' : 'Queued to generate widget…',
            timing: 'Timing starts when generation begins.',
        }
    }
    if (phase.startsWith('publishing')) {
        return {
            detail: 'Preparing the interactive preview.',
            isOverEstimate: false,
            label: 'Publishing widget…',
            timing: 'The preview build usually takes less than a minute.',
        }
    }
    const modelInfo = WIDGET_MODEL_INFO[model]
    const secondsFromEstimate = elapsedSeconds - modelInfo.estimatedSeconds
    const isOverEstimate = secondsFromEstimate > 0
    return {
        detail: `${modelInfo.name} is writing the widget source. You can leave this page and come back later.`,
        isOverEstimate,
        label: hasVersions ? 'Regenerating widget…' : 'Generating widget…',
        timing: isOverEstimate
            ? `Typical: ${modelInfo.estimateLabel} · ${formatWidgetElapsed(secondsFromEstimate)} longer than usual. Generation is still in progress.`
            : `Typical: ${modelInfo.estimateLabel} · Estimated remaining: ${formatWidgetElapsed(
                  modelInfo.estimatedSeconds - elapsedSeconds
              )}`,
    }
}

export async function loadWidgetFrame(
    projectId: string,
    notebookShortId: string,
    nodeId: string,
    versionId: string,
    frameName: string,
    offset: number,
    limit: number,
    signal: AbortSignal
): Promise<WidgetFrameApi> {
    return await notebooksWidgetFrame(
        projectId,
        notebookShortId,
        nodeId,
        frameName,
        {
            version_id: versionId,
            offset,
            limit,
        },
        { signal }
    )
}

export const notebookNodeGeneratedWidgetLogic: LogicWrapper<notebookNodeGeneratedWidgetLogicType> =
    kea<notebookNodeGeneratedWidgetLogicType>([
        props({} as NotebookNodeGeneratedWidgetLogicProps),
        key((props) => `${props.notebookShortId}-${props.nodeId}`),
        path((key) => ['products', 'notebooks', 'notebookNodeGeneratedWidgetLogic', key]),
        connect((props: NotebookNodeGeneratedWidgetLogicProps) => ({
            values: [
                teamLogic,
                ['currentTeamId'],
                notebookNodeStalenessLogic({ shortId: props.notebookShortId }),
                ['isChainRunning as isCellChainRunning'],
                notebookOperationsLogic({ shortId: props.notebookShortId }),
                ['isBusy as isNotebookBusy'],
            ],
            actions: [
                notebookNodeStalenessLogic({ shortId: props.notebookShortId }),
                ['cellChainFinished', 'runCellChain'],
            ],
        })),
        actions({
            artifactAvailable: true,
            artifactRefreshReady: true,
            artifactUnavailable: true,
            cancelGeneration: true,
            cancellationFailed: (error: string) => ({ error }),
            cancellationStarted: true,
            dataRunFinished: (success: boolean, error: string | null) => ({ success, error }),
            dataRunStarted: (requestId: string) => ({ requestId }),
            closeGenerationModal: true,
            closeSourceEditor: true,
            generateWidget: (prompt: string, model: WidgetModel, operation: WidgetGenerationOperation) => ({
                prompt,
                model,
                operation,
            }),
            generationCanceled: true,
            generationFailed: (error: string) => ({ error }),
            generationRequestFinished: true,
            generationRequestStarted: true,
            loadMoreVersions: true,
            loadStatus: true,
            loadVersions: (reset: boolean) => ({ reset }),
            openGenerationModal: (operation: Exclude<WidgetGenerationOperation, 'initial'>) => ({ operation }),
            openSourceEditor: true,
            refreshData: true,
            runWidget: true,
            restoreFailed: (error: string) => ({ error }),
            restoreSelectedVersion: true,
            restoreStarted: true,
            saveSource: true,
            selectVersion: (versionId: string) => ({ versionId }),
            setGenerationDraftLoading: (loading: boolean) => ({ loading }),
            setGenerationDraftModel: (model: WidgetModel) => ({ model }),
            setGenerationDraftPrompt: (prompt: string) => ({ prompt }),
            setRuntimeError: (error: string | null) => ({ error }),
            setSourceDraft: (source: string) => ({ source }),
            setSourceNote: (note: string) => ({ note }),
            sourceFailed: (error: string) => ({ error }),
            sourceLoadStarted: true,
            sourceReceived: (source: WidgetSourceResponseApi) => ({ source }),
            sourceSaveStarted: true,
            sourceSaved: true,
            statusFailed: (error: string) => ({ error }),
            statusReceived: (status: WidgetStatusApi) => ({ status }),
            tickElapsed: (elapsedSeconds: number) => ({ elapsedSeconds }),
            versionsFailed: (error: string) => ({ error }),
            versionsReceived: (
                versions: WidgetVersionApi[],
                count: number,
                nextOffset: number | null,
                reset: boolean
            ) => ({ versions, count, nextOffset, reset }),
        }),
        reducers(({ props }) => ({
            activeDataRunRequestId: [
                null as string | null,
                {
                    dataRunStarted: (_, { requestId }) => requestId,
                    dataRunFinished: () => null,
                },
            ],
            activeGenerationModel: [
                props.model,
                {
                    generateWidget: (_, { model }) => model,
                    statusReceived: (activeModel, { status }) =>
                        isWidgetModel(status.active_job?.model) ? status.active_job.model : activeModel,
                },
            ],
            artifactUnavailable: [
                false,
                {
                    artifactAvailable: () => false,
                    artifactRefreshReady: () => false,
                    artifactUnavailable: () => true,
                    selectVersion: () => false,
                    statusReceived: (unavailable, { status }) => (status.artifact_url ? false : unavailable),
                },
            ],
            cancellationInFlight: [
                false,
                {
                    cancellationStarted: () => true,
                    cancellationFailed: () => false,
                    generationCanceled: () => false,
                },
            ],
            elapsedSeconds: [0, { tickElapsed: (_, { elapsedSeconds }) => elapsedSeconds }],
            dataRunInFlight: [
                false,
                {
                    dataRunStarted: () => true,
                    dataRunFinished: () => false,
                },
            ],
            frameRevision: [
                0,
                {
                    artifactRefreshReady: (revision) => revision + 1,
                    sourceSaved: (revision) => revision + 1,
                },
            ],
            generationDraftLoading: [
                false,
                { setGenerationDraftLoading: (_, { loading }) => loading, closeGenerationModal: () => false },
            ],
            generationDraftModel: [DEFAULT_WIDGET_MODEL, { setGenerationDraftModel: (_, { model }) => model }],
            generationDraftPrompt: ['', { setGenerationDraftPrompt: (_, { prompt }) => prompt }],
            generationError: [
                null as string | null,
                {
                    generateWidget: () => null,
                    generationCanceled: () => null,
                    generationFailed: (_, { error }) => error,
                    cancellationFailed: (_, { error }) => error,
                    restoreFailed: (_, { error }) => error,
                    restoreStarted: () => null,
                },
            ],
            generationModalOperation: [
                null as WidgetGenerationModalOperation,
                {
                    closeGenerationModal: () => null,
                    openGenerationModal: (_, { operation }) => operation,
                },
            ],
            generationRequestLoading: [
                false,
                {
                    generationRequestStarted: () => true,
                    generationRequestFinished: () => false,
                },
            ],
            restoreInFlight: [
                false,
                {
                    restoreStarted: () => true,
                    restoreFailed: () => false,
                    statusReceived: () => false,
                },
            ],
            runtimeError: [
                null as string | null,
                {
                    setRuntimeError: (_, { error }) => error,
                    dataRunStarted: () => null,
                    artifactRefreshReady: () => null,
                    selectVersion: () => null,
                },
            ],
            selectedVersionId: [
                null as string | null,
                {
                    selectVersion: (_, { versionId }) => versionId,
                    statusReceived: (selectedVersionId, { status }) => selectedVersionId ?? status.current_version_id,
                    versionsReceived: (selectedVersionId, { versions, reset }) =>
                        reset && selectedVersionId && !versions.some(({ id }) => id === selectedVersionId)
                            ? (versions.find(({ is_current }) => is_current)?.id ?? selectedVersionId)
                            : selectedVersionId,
                },
            ],
            sourceDraft: [
                '',
                {
                    setSourceDraft: (_, { source }) => source,
                    sourceLoadStarted: () => '',
                    sourceReceived: (_, { source }) => source.source,
                },
            ],
            sourceError: [
                null as string | null,
                {
                    sourceLoadStarted: () => null,
                    sourceSaveStarted: () => null,
                    sourceFailed: (_, { error }) => error,
                    sourceReceived: () => null,
                },
            ],
            sourceLoading: [
                false,
                {
                    sourceLoadStarted: () => true,
                    sourceFailed: () => false,
                    sourceReceived: () => false,
                },
            ],
            sourceModalOpen: [false, { openSourceEditor: () => true, closeSourceEditor: () => false }],
            sourceNote: [
                '',
                {
                    closeSourceEditor: () => '',
                    setSourceNote: (_, { note }) => note,
                    sourceReceived: () => '',
                },
            ],
            sourceSaving: [
                false,
                {
                    sourceSaveStarted: () => true,
                    sourceFailed: () => false,
                    sourceSaved: () => false,
                },
            ],
            status: [null as WidgetStatusApi | null, { statusReceived: (_, { status }) => status }],
            statusLoadError: [
                null as string | null,
                {
                    loadStatus: () => null,
                    statusFailed: (_, { error }) => error,
                    statusReceived: () => null,
                },
            ],
            statusLoading: [false, { loadStatus: () => true, statusFailed: () => false, statusReceived: () => false }],
            versions: [
                [] as WidgetVersionApi[],
                {
                    versionsReceived: (current, { versions, reset }) => (reset ? versions : [...current, ...versions]),
                    statusReceived: (current, { status }) => (status.has_versions ? current : []),
                },
            ],
            versionsCount: [0, { versionsReceived: (_, { count }) => count }],
            versionsError: [
                null as string | null,
                {
                    loadVersions: () => null,
                    versionsFailed: (_, { error }) => error,
                    versionsReceived: () => null,
                },
            ],
            versionsLoading: [
                false,
                { loadVersions: () => true, versionsFailed: () => false, versionsReceived: () => false },
            ],
            versionsNextOffset: [null as number | null, { versionsReceived: (_, { nextOffset }) => nextOffset }],
        })),
        selectors({
            activeFrameNames: [
                (selectors) => [selectors.selectedVersion, selectors.selectedVersionId, selectors.status],
                (selectedVersion, selectedVersionId, status): string[] =>
                    selectedVersion?.frame_names ??
                    (selectedVersionId === status?.current_version_id ? (status?.frame_names ?? []) : []),
            ],
            selectedVersion: [
                (selectors) => [selectors.versions, selectors.selectedVersionId],
                (versions: WidgetVersionApi[], selectedVersionId: string | null): WidgetVersionApi | null =>
                    versions.find(({ id }) => id === selectedVersionId) ?? null,
            ],
            isWorking: [
                (selectors) => [selectors.status],
                (status: WidgetStatusApi | null): boolean => shouldPoll(status),
            ],
            workingStatus: [
                (selectors) => [selectors.activeGenerationModel, selectors.elapsedSeconds, selectors.status],
                (activeGenerationModel, elapsedSeconds, status): WidgetWorkingStatus | null => {
                    if (!shouldPoll(status)) {
                        return null
                    }
                    return getWidgetWorkingStatus({
                        elapsedSeconds,
                        hasVersions: Boolean(status?.has_versions),
                        model: activeGenerationModel,
                        phase:
                            status?.active_job?.phase ??
                            (status?.lifecycle_status === 'building' ? 'publishing' : 'generating'),
                    })
                },
            ],
        }),
        listeners(({ actions, values, props, cache }) => {
            const scheduleStatusPoll = (): void => {
                cache.disposables.dispose('statusPoll')
                if (document.hidden) {
                    return
                }
                const failureCount = Number(cache.statusPollFailures ?? 0)
                const delay = Math.min(STATUS_POLL_INTERVAL_MS * 2 ** failureCount, STATUS_POLL_MAX_INTERVAL_MS)
                cache.disposables.add(() => {
                    const timeoutId = window.setTimeout(() => actions.loadStatus(), delay)
                    return () => window.clearTimeout(timeoutId)
                }, 'statusPoll')
            }

            const startElapsedClock = (startedAt: number): void => {
                cache.generationStartedAt = startedAt
                cache.disposables.dispose('elapsedClock')
                const updateElapsed = (): void => {
                    actions.tickElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1_000)))
                }
                updateElapsed()
                cache.disposables.add(() => {
                    const intervalId = window.setInterval(updateElapsed, 1_000)
                    return () => window.clearInterval(intervalId)
                }, 'elapsedClock')
            }

            return {
                cellChainFinished: ({ requestId, success }) => {
                    if (requestId !== values.activeDataRunRequestId) {
                        return
                    }
                    actions.dataRunFinished(
                        success,
                        success
                            ? null
                            : 'Widget data could not be refreshed because a cell did not finish successfully.'
                    )
                },
                cancelGeneration: async () => {
                    const generationId = values.status?.active_job?.id
                    if (!props.isEditable || !generationId || !values.currentTeamId || values.cancellationInFlight) {
                        return
                    }
                    actions.cancellationStarted()
                    try {
                        await notebooksWidgetCancel(String(values.currentTeamId), props.notebookShortId, props.nodeId, {
                            generation_id: generationId,
                        })
                        actions.generationCanceled()
                        actions.loadStatus()
                    } catch (error) {
                        const message = errorMessage(error)
                        posthog.captureException(error instanceof Error ? error : new Error(message), {
                            action: 'cancel notebook widget generation',
                        })
                        actions.cancellationFailed(message)
                    }
                },
                generateWidget: async ({ prompt, model, operation }) => {
                    if (!props.isEditable || values.generationRequestLoading || values.isWorking) {
                        return
                    }
                    if (!values.currentTeamId) {
                        actions.generationFailed('The current project is unavailable. Refresh and try again.')
                        return
                    }
                    if (!prompt.trim()) {
                        actions.generationFailed(
                            operation === 'improve'
                                ? 'Describe the change you want to make.'
                                : 'Add instructions before generating the widget.'
                        )
                        return
                    }
                    actions.generationRequestStarted()
                    const generationId = uuidv4()
                    try {
                        const requestGeneration = async (): Promise<WidgetStatusApi> =>
                            await notebooksWidgetGenerate(
                                String(values.currentTeamId),
                                props.notebookShortId,
                                props.nodeId,
                                { prompt, generation_id: generationId, model, operation }
                            )
                        let queuedStatus: WidgetStatusApi
                        try {
                            queuedStatus = await requestGeneration()
                        } catch (error) {
                            if (!isMissingNodeError(error)) {
                                throw error
                            }
                            await props.persistNotebook()
                            queuedStatus = await requestGeneration()
                        }
                        actions.closeGenerationModal()
                        actions.statusReceived(queuedStatus)
                    } catch (error) {
                        const message = errorMessage(error)
                        posthog.captureException(error instanceof Error ? error : new Error(message), {
                            action: 'generate notebook widget',
                        })
                        actions.generationFailed(message)
                    } finally {
                        actions.generationRequestFinished()
                    }
                },
                loadMoreVersions: () => {
                    if (values.versionsNextOffset !== null) {
                        actions.loadVersions(false)
                    }
                },
                refreshData: async () => {
                    if (!values.currentTeamId) {
                        actions.statusFailed('The current project is unavailable. Refresh and try again.')
                        return
                    }
                    try {
                        actions.statusReceived(
                            await notebooksWidgetStatus(
                                String(values.currentTeamId),
                                props.notebookShortId,
                                props.nodeId
                            )
                        )
                        actions.artifactRefreshReady()
                    } catch (error) {
                        actions.statusFailed(errorMessage(error))
                    }
                },
                loadStatus: async () => {
                    if (!values.currentTeamId) {
                        return
                    }
                    try {
                        actions.statusReceived(
                            await notebooksWidgetStatus(
                                String(values.currentTeamId),
                                props.notebookShortId,
                                props.nodeId
                            )
                        )
                    } catch (error) {
                        actions.statusFailed(errorMessage(error))
                    }
                },
                loadVersions: async ({ reset }) => {
                    if (!values.currentTeamId) {
                        actions.versionsFailed('The current project is unavailable.')
                        return
                    }
                    if (cache.versionsRequestInFlight) {
                        if (reset) {
                            cache.versionsResetPending = true
                        }
                        return
                    }
                    cache.versionsRequestInFlight = true
                    const offset = reset ? 0 : (values.versionsNextOffset ?? values.versions.length)
                    try {
                        const page = await notebooksWidgetVersions(
                            String(values.currentTeamId),
                            props.notebookShortId,
                            props.nodeId,
                            { offset, limit: VERSION_PAGE_SIZE }
                        )
                        actions.versionsReceived(page.results, page.count, page.next_offset, reset)
                    } catch (error) {
                        actions.versionsFailed(errorMessage(error))
                    } finally {
                        cache.versionsRequestInFlight = false
                        if (cache.versionsResetPending) {
                            cache.versionsResetPending = false
                            actions.loadVersions(true)
                        }
                    }
                },
                openGenerationModal: async ({ operation }) => {
                    const fallbackPrompt = operation === 'regenerate' ? props.prompt : ''
                    actions.setGenerationDraftPrompt(fallbackPrompt)
                    actions.setGenerationDraftModel(
                        isWidgetModel(values.selectedVersion?.model) ? values.selectedVersion.model : props.model
                    )
                    if (operation !== 'regenerate' || !values.currentTeamId || !values.selectedVersionId) {
                        return
                    }
                    actions.setGenerationDraftLoading(true)
                    try {
                        const source = await notebooksWidgetSource(
                            String(values.currentTeamId),
                            props.notebookShortId,
                            props.nodeId,
                            { version_id: values.selectedVersionId }
                        )
                        if (source.effective_prompt.trim()) {
                            actions.setGenerationDraftPrompt(source.effective_prompt)
                        }
                    } catch (error) {
                        if (!fallbackPrompt.trim()) {
                            actions.generationFailed(errorMessage(error))
                        }
                    } finally {
                        actions.setGenerationDraftLoading(false)
                    }
                },
                openSourceEditor: async () => {
                    if (!values.currentTeamId || !values.selectedVersionId) {
                        return
                    }
                    actions.sourceLoadStarted()
                    try {
                        actions.sourceReceived(
                            await notebooksWidgetSource(
                                String(values.currentTeamId),
                                props.notebookShortId,
                                props.nodeId,
                                {
                                    version_id: values.selectedVersionId,
                                }
                            )
                        )
                    } catch (error) {
                        actions.sourceFailed(errorMessage(error))
                    }
                },
                dataRunFinished: ({ success, error }) => {
                    if (success) {
                        actions.refreshData()
                    } else if (error) {
                        actions.setRuntimeError(error)
                    }
                },
                runWidget: async () => {
                    if (
                        !props.isEditable ||
                        values.dataRunInFlight ||
                        values.isCellChainRunning ||
                        values.isNotebookBusy
                    ) {
                        return
                    }
                    if (!values.activeFrameNames.length) {
                        actions.refreshData()
                        return
                    }
                    if (!values.currentTeamId) {
                        actions.setRuntimeError('The current project is unavailable. Refresh and try again.')
                        return
                    }

                    const requestId = uuidv4()
                    actions.dataRunStarted(requestId)
                    try {
                        await props.persistNotebook()
                        const state = await notebooksSqlV2StateRetrieve(
                            String(values.currentTeamId),
                            props.notebookShortId
                        )
                        const plan = buildWidgetDataRunPlan(state.cells, values.activeFrameNames)
                        if (plan.missingFrameName) {
                            actions.dataRunFinished(
                                false,
                                `Dataframe "${plan.missingFrameName}" is no longer in this notebook.`
                            )
                            return
                        }
                        actions.runCellChain(plan.nodeIds, requestId)
                    } catch (error) {
                        actions.dataRunFinished(false, errorMessage(error))
                    }
                },
                restoreSelectedVersion: async () => {
                    if (
                        !props.isEditable ||
                        !values.currentTeamId ||
                        !values.selectedVersionId ||
                        !values.status?.current_version_id ||
                        values.selectedVersionId === values.status.current_version_id ||
                        values.restoreInFlight
                    ) {
                        return
                    }
                    actions.restoreStarted()
                    try {
                        const restoredStatus = await notebooksWidgetRevert(
                            String(values.currentTeamId),
                            props.notebookShortId,
                            props.nodeId,
                            {
                                version_id: values.selectedVersionId,
                                expected_current_version_id: values.status.current_version_id,
                            }
                        )
                        actions.statusReceived(restoredStatus)
                        if (restoredStatus.current_version_id) {
                            actions.selectVersion(restoredStatus.current_version_id)
                        }
                        actions.loadVersions(true)
                        actions.refreshData()
                    } catch (error) {
                        actions.restoreFailed(errorMessage(error))
                    }
                },
                saveSource: async () => {
                    if (
                        !props.isEditable ||
                        !values.currentTeamId ||
                        !values.status?.current_version_id ||
                        values.selectedVersionId !== values.status.current_version_id ||
                        !values.sourceDraft.trim() ||
                        !values.sourceNote.trim() ||
                        values.sourceSaving
                    ) {
                        return
                    }
                    actions.sourceSaveStarted()
                    try {
                        const savedStatus = await notebooksWidgetSaveSource(
                            String(values.currentTeamId),
                            props.notebookShortId,
                            props.nodeId,
                            {
                                source: values.sourceDraft,
                                prompt: values.sourceNote,
                                expected_current_version_id: values.status.current_version_id,
                            }
                        )
                        actions.statusReceived(savedStatus)
                        if (savedStatus.current_version_id) {
                            actions.selectVersion(savedStatus.current_version_id)
                        }
                        actions.sourceSaved()
                        actions.closeSourceEditor()
                        actions.loadVersions(true)
                    } catch (error) {
                        actions.sourceFailed(errorMessage(error))
                    }
                },
                statusReceived: ({ status }) => {
                    cache.statusPollFailures = 0
                    cache.disposables.dispose('statusPoll')
                    if (status.has_versions && (!values.versions.length || !values.selectedVersionId)) {
                        actions.loadVersions(true)
                    }
                    if (
                        status.current_version_id &&
                        cache.currentVersionId &&
                        cache.currentVersionId !== status.current_version_id
                    ) {
                        actions.selectVersion(status.current_version_id)
                        actions.loadVersions(true)
                    }
                    cache.currentVersionId = status.current_version_id
                    if (shouldPoll(status)) {
                        scheduleStatusPoll()
                        const startedAtRaw = status.active_job?.started_at ?? status.active_job?.created_at
                        const startedAt = startedAtRaw
                            ? new Date(startedAtRaw).getTime()
                            : (cache.generationStartedAt ?? Date.now())
                        if (startedAt !== cache.generationStartedAt) {
                            startElapsedClock(startedAt)
                        }
                    } else {
                        cache.disposables.dispose('elapsedClock')
                        cache.generationStartedAt = null
                    }
                },
                statusFailed: () => {
                    if (shouldPoll(values.status)) {
                        cache.statusPollFailures = Number(cache.statusPollFailures ?? 0) + 1
                        scheduleStatusPoll()
                    }
                },
            }
        }),
        afterMount(({ actions, cache }) => {
            cache.disposables.add(() => {
                const handleVisibilityChange = (): void => {
                    if (document.hidden) {
                        cache.disposables.dispose('statusPoll')
                    } else {
                        actions.loadStatus()
                    }
                }
                document.addEventListener('visibilitychange', handleVisibilityChange)
                return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
            }, 'visibilityChange')
            actions.loadStatus()
        }),
    ])
