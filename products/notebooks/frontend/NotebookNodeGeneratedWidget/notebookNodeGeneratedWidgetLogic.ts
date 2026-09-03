import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
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

import { ApiError, isAbortError } from 'lib/api'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import {
    buildNotebookDependencyGraph,
    collectDependencyNodeIds,
    collectNotebookFrameNodes,
} from 'scenes/notebooks/Nodes/notebookNodeContent'
import { notebookNodeStalenessLogic } from 'scenes/notebooks/Notebook/notebookNodeStalenessLogic'
import { notebookOperationsLogic } from 'scenes/notebooks/Notebook/notebookOperationsLogic'
import { NotebookNodeType } from 'scenes/notebooks/types'

import {
    notebooksWidgetCancel,
    notebooksWidgetFrame,
    notebooksWidgetGenerate,
    notebooksWidgetRevert,
    notebooksWidgetSource,
    notebooksWidgetStatus,
    notebooksWidgetVersions,
} from 'products/notebooks/frontend/generated/api'
import type {
    WidgetFrameApi,
    WidgetStatusApi,
    WidgetVersionApi,
} from 'products/notebooks/frontend/generated/api.schemas'

import {
    DEFAULT_WIDGET_MODEL,
    DEFAULT_WIDGET_PROMPT,
    MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH,
    MAX_WIDGET_PROMPT_LENGTH,
    WIDGET_MODEL_INFO,
    isWidgetModel,
    type WidgetModel,
} from './widgetModels'

const STATUS_POLL_INTERVAL_MS = 2_000
const STATUS_POLL_MAX_INTERVAL_MS = 30_000
const WIDGET_REQUEST_TIMEOUT_MS = 30_000
const VERSION_PAGE_SIZE = 25
const SAFE_WIDGET_NODE_ID = /^[A-Za-z0-9_-]{1,128}$/

export type WidgetGenerationOperation = 'initial' | 'regenerate' | 'improve'
export type WidgetGenerationModalOperation = Exclude<WidgetGenerationOperation, 'initial'> | null

export type WidgetWorkingStatus = {
    detail: string
    isOverEstimate: boolean
    label: string
    timing: string
}

export type NotebookNodeGeneratedWidgetLogicProps = {
    projectId: number | null
    notebookShortId: string
    nodeId: string
    prompt: string
    model: WidgetModel
    isEditable: boolean
    persistNotebook: () => Promise<void>
    getContent: () => JSONContent | null
}

export interface notebookNodeGeneratedWidgetLogicValues {
    activeGenerationModel: WidgetModel
    artifactLoading: boolean
    activeFrameNames: string[]
    artifactUnavailable: boolean
    cancellationInFlight: boolean
    dataRefreshInFlight: boolean
    elapsedSeconds: number
    frameRevision: number
    generationDraftModel: WidgetModel
    generationDraftPrompt: string
    generationError: string | null
    generationModalOperation: WidgetGenerationModalOperation
    generationRequestLoading: boolean
    isDataChainRunning: boolean
    isWorking: boolean
    notebookIsBusy: boolean
    restoreInFlight: boolean
    runDataDependenciesDisabledReason: string | null
    runtimeError: string | null
    selectedVersion: WidgetVersionApi | null
    selectedVersionId: string | null
    status: WidgetStatusApi | null
    statusLoadError: string | null
    statusLoading: boolean
    source: string | null
    sourceChangePrompt: string
    sourceError: string | null
    sourceLoading: boolean
    sourceModalOpen: boolean
    sourceImprovementDisabledReason: string | null
    sourceVersionId: string | null
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
    abortChain: (reason: string | null) => { reason: string | null }
    cancelGeneration: () => { value: true }
    cancellationFailed: (error: string) => { error: string }
    cancellationStarted: () => { value: true }
    clearGenerationError: () => { value: true }
    closeGenerationModal: () => { value: true }
    closeSourceModal: () => { value: true }
    dataRefreshFinished: () => { value: true }
    dataRefreshStarted: () => { value: true }
    generateWidget: (
        prompt: string,
        model: WidgetModel,
        operation: WidgetGenerationOperation,
        expectedCurrentVersionId?: string
    ) => {
        prompt: string
        model: WidgetModel
        operation: WidgetGenerationOperation
        expectedCurrentVersionId?: string
    }
    generationCanceled: () => { value: true }
    generationFailed: (error: string) => { error: string }
    generationRequestFinished: () => { value: true }
    generationRequestStarted: () => { value: true }
    improveSource: () => { value: true }
    loadMoreVersions: () => { value: true }
    loadSource: () => { value: true }
    loadStatus: () => { value: true }
    loadVersions: (reset: boolean) => { reset: boolean }
    openGenerationModal: (operation: Exclude<WidgetGenerationOperation, 'initial'>) => {
        operation: 'regenerate' | 'improve'
    }
    openSourceModal: () => { value: true }
    refreshData: () => { value: true }
    runDataDependencies: () => { value: true }
    runWidgetDataChain: (
        content: JSONContent | null,
        nodeIds: string[]
    ) => {
        content: JSONContent | null
        nodeIds: string[]
    }
    restoreFailed: (error: string) => { error: string }
    restoreSelectedVersion: () => { value: true }
    restoreStarted: () => { value: true }
    selectVersion: (versionId: string) => { versionId: string }
    setGenerationDraftModel: (model: WidgetModel) => { model: WidgetModel }
    setGenerationDraftPrompt: (prompt: string) => { prompt: string }
    setRuntimeError: (error: string | null) => { error: string | null }
    setSourceChangePrompt: (prompt: string) => { prompt: string }
    sourceFailed: (error: string) => { error: string }
    sourceReceived: (source: string, versionId: string | null) => { source: string; versionId: string | null }
    statusFailed: (error: string) => { error: string }
    statusReceived: (status: WidgetStatusApi) => { status: WidgetStatusApi }
    statusRequestFinished: () => { value: true }
    statusRequestStarted: () => { value: true }
    tickElapsed: (elapsedSeconds: number) => { elapsedSeconds: number }
    versionRefreshed: (version: WidgetVersionApi) => { version: WidgetVersionApi }
    versionsFailed: (error: string) => { error: string }
    versionsReceived: (
        versions: WidgetVersionApi[],
        count: number,
        nextOffset: number | null,
        reset: boolean
    ) => { versions: WidgetVersionApi[]; count: number; nextOffset: number | null; reset: boolean }
    widgetDataChainFinished: (nodeIds: string[]) => { nodeIds: string[] }
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

interface notebookNodeGeneratedWidgetSettingsLogicActions {
    loadVersions: (reset: boolean) => { reset: boolean }
}

interface notebookNodeGeneratedWidgetSettingsLogicMeta {
    key: string
}

type notebookNodeGeneratedWidgetSettingsLogicType = MakeLogicType<
    {},
    notebookNodeGeneratedWidgetSettingsLogicActions,
    NotebookNodeGeneratedWidgetLogicProps,
    notebookNodeGeneratedWidgetSettingsLogicMeta
>

function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        const response = error.data as Record<string, unknown> | undefined
        if (typeof response?.detail === 'string') {
            return response.detail
        }
        const fieldError = Object.values(response ?? {}).find(
            (value): value is string[] => Array.isArray(value) && typeof value[0] === 'string'
        )
        if (fieldError) {
            return fieldError[0]
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

function isAmbiguousMutationError(error: unknown): boolean {
    return !(error instanceof ApiError) || error.status === undefined || error.status >= 500
}

function shouldPoll(status: WidgetStatusApi | null): boolean {
    return (
        Boolean(status?.active_job) ||
        status?.lifecycle_status === 'generating' ||
        status?.lifecycle_status === 'building'
    )
}

export function isSafeWidgetNodeId(nodeId: string): boolean {
    return SAFE_WIDGET_NODE_ID.test(nodeId)
}

export function getWidgetDataDependencies(
    content: JSONContent | null,
    frameNames: string[]
): { missingFrameNames: string[]; nodeIds: string[] } {
    if (!content || !frameNames.length) {
        return { missingFrameNames: [], nodeIds: [] }
    }
    const graph = buildNotebookDependencyGraph(content)
    const frameNodes = collectNotebookFrameNodes(content)
    const owners = new Map<string, string>()
    for (const nodeType of ['sql', 'python'] as const) {
        for (const node of frameNodes) {
            if (node.nodeType === nodeType && node.nodeId && !owners.has(node.name)) {
                owners.set(node.name, node.nodeId)
            }
        }
    }
    const connectedNodeIds = new Set<string>()
    const missingFrameNames: string[] = []
    for (const frameName of frameNames) {
        const ownerNodeId = owners.get(frameName)
        if (!ownerNodeId) {
            missingFrameNames.push(frameName)
            continue
        }
        for (const nodeId of collectDependencyNodeIds(graph, ownerNodeId, 'upstream')) {
            connectedNodeIds.add(nodeId)
        }
    }
    return {
        missingFrameNames,
        nodeIds: graph.nodes
            .filter(
                (node) =>
                    connectedNodeIds.has(node.nodeId) &&
                    (node.nodeType === NotebookNodeType.SQLV2 || node.nodeType === NotebookNodeType.PythonV2)
            )
            .map((node) => node.nodeId),
    }
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
    if (phase.startsWith('reviewing')) {
        return {
            detail: 'Checking the generated source for security issues.',
            isOverEstimate: false,
            label: 'Reviewing widget security…',
            timing: 'This usually takes less than a minute.',
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
    runId: string | undefined,
    signal: AbortSignal
): Promise<WidgetFrameApi> {
    if (!isSafeWidgetNodeId(nodeId)) {
        throw new Error('This widget has an invalid identifier.')
    }
    return await notebooksWidgetFrame(
        projectId,
        notebookShortId,
        nodeId,
        frameName,
        {
            version_id: versionId,
            run_id: runId,
            offset,
            limit,
        },
        { signal }
    )
}

export const notebookNodeGeneratedWidgetLogic: LogicWrapper<notebookNodeGeneratedWidgetLogicType> =
    kea<notebookNodeGeneratedWidgetLogicType>([
        props({} as NotebookNodeGeneratedWidgetLogicProps),
        key((props) => `${props.projectId}-${props.notebookShortId}-${props.nodeId}`),
        path((key) => ['products', 'notebooks', 'notebookNodeGeneratedWidgetLogic', key]),
        connect((props: NotebookNodeGeneratedWidgetLogicProps) => ({
            values: [
                notebookNodeStalenessLogic({ shortId: props.notebookShortId }),
                ['isChainRunning as isDataChainRunning'],
                notebookOperationsLogic({ shortId: props.notebookShortId }),
                ['isBusy as notebookIsBusy'],
            ],
            actions: [
                notebookNodeStalenessLogic({ shortId: props.notebookShortId }),
                ['abortChain', 'runWidgetDataChain', 'widgetDataChainFinished'],
            ],
        })),
        actions({
            artifactAvailable: true,
            artifactRefreshReady: true,
            artifactUnavailable: true,
            cancelGeneration: true,
            cancellationFailed: (error: string) => ({ error }),
            cancellationStarted: true,
            clearGenerationError: true,
            closeGenerationModal: true,
            closeSourceModal: true,
            dataRefreshFinished: true,
            dataRefreshStarted: true,
            generateWidget: (
                prompt: string,
                model: WidgetModel,
                operation: WidgetGenerationOperation,
                expectedCurrentVersionId?: string
            ) => ({
                prompt,
                model,
                operation,
                expectedCurrentVersionId,
            }),
            generationCanceled: true,
            generationFailed: (error: string) => ({ error }),
            generationRequestFinished: true,
            generationRequestStarted: true,
            improveSource: true,
            loadMoreVersions: true,
            loadSource: true,
            loadStatus: true,
            loadVersions: (reset: boolean) => ({ reset }),
            openGenerationModal: (operation: Exclude<WidgetGenerationOperation, 'initial'>) => ({ operation }),
            openSourceModal: true,
            refreshData: true,
            runDataDependencies: true,
            restoreFailed: (error: string) => ({ error }),
            restoreSelectedVersion: true,
            restoreStarted: true,
            selectVersion: (versionId: string) => ({ versionId }),
            setGenerationDraftModel: (model: WidgetModel) => ({ model }),
            setGenerationDraftPrompt: (prompt: string) => ({ prompt }),
            setRuntimeError: (error: string | null) => ({ error }),
            setSourceChangePrompt: (prompt: string) => ({ prompt }),
            sourceFailed: (error: string) => ({ error }),
            sourceReceived: (source: string, versionId: string | null) => ({ source, versionId }),
            statusFailed: (error: string) => ({ error }),
            statusReceived: (status: WidgetStatusApi) => ({ status }),
            statusRequestFinished: true,
            statusRequestStarted: true,
            tickElapsed: (elapsedSeconds: number) => ({ elapsedSeconds }),
            versionsFailed: (error: string) => ({ error }),
            versionRefreshed: (version: WidgetVersionApi) => ({ version }),
            versionsReceived: (
                versions: WidgetVersionApi[],
                count: number,
                nextOffset: number | null,
                reset: boolean
            ) => ({ versions, count, nextOffset, reset }),
        }),
        reducers(({ props }) => ({
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
                    generateWidget: () => false,
                    selectVersion: () => false,
                    statusReceived: (unavailable, { status }) => (status.artifact_url ? false : unavailable),
                },
            ],
            artifactLoading: [
                true,
                {
                    artifactAvailable: () => false,
                    artifactRefreshReady: () => true,
                    artifactUnavailable: () => false,
                    selectVersion: () => true,
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
            frameRevision: [
                0,
                {
                    artifactRefreshReady: (revision) => revision + 1,
                },
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
                    clearGenerationError: () => null,
                    restoreFailed: (_, { error }) => error,
                    restoreStarted: () => null,
                    statusReceived: (error, { status }) => (status.lifecycle_status === 'ready' ? null : error),
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
            dataRefreshInFlight: [
                false,
                {
                    artifactRefreshReady: () => false,
                    dataRefreshStarted: () => true,
                    dataRefreshFinished: () => false,
                    abortChain: () => false,
                    refreshData: () => true,
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
                    artifactRefreshReady: () => null,
                    generateWidget: () => null,
                    selectVersion: () => null,
                },
            ],
            source: [null as string | null, { openSourceModal: () => null, sourceReceived: (_, { source }) => source }],
            sourceChangePrompt: ['', { openSourceModal: () => '', setSourceChangePrompt: (_, { prompt }) => prompt }],
            sourceError: [
                null as string | null,
                { loadSource: () => null, sourceFailed: (_, { error }) => error, sourceReceived: () => null },
            ],
            sourceLoading: [
                false,
                {
                    closeSourceModal: () => false,
                    loadSource: () => true,
                    sourceFailed: () => false,
                    sourceReceived: () => false,
                },
            ],
            sourceModalOpen: [false, { closeSourceModal: () => false, openSourceModal: () => true }],
            sourceVersionId: [
                null as string | null,
                {
                    openSourceModal: () => null,
                    sourceReceived: (_, { versionId }) => versionId,
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
            status: [null as WidgetStatusApi | null, { statusReceived: (_, { status }) => status }],
            statusLoadError: [
                null as string | null,
                {
                    loadStatus: () => null,
                    statusFailed: (_, { error }) => error,
                    statusReceived: () => null,
                },
            ],
            statusLoading: [
                false,
                {
                    statusFailed: () => false,
                    statusReceived: () => false,
                    statusRequestFinished: () => false,
                    statusRequestStarted: () => true,
                },
            ],
            versions: [
                [] as WidgetVersionApi[],
                {
                    versionsReceived: (current, { versions, reset }) => (reset ? versions : [...current, ...versions]),
                    versionRefreshed: (current, { version }) =>
                        current.map((candidate) => (candidate.id === version.id ? version : candidate)),
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
            runDataDependenciesDisabledReason: [
                (selectors) => [
                    selectors.activeFrameNames,
                    selectors.dataRefreshInFlight,
                    selectors.isDataChainRunning,
                    selectors.isWorking,
                    selectors.notebookIsBusy,
                    selectors.status,
                    selectors.statusLoading,
                ],
                (
                    activeFrameNames,
                    dataRefreshInFlight,
                    isDataChainRunning,
                    isWorking,
                    notebookIsBusy,
                    status,
                    statusLoading
                ): string | null => {
                    if (dataRefreshInFlight) {
                        return null
                    }
                    if (isWorking) {
                        return 'Wait for widget generation to finish.'
                    }
                    if (statusLoading && !status) {
                        return 'Loading widget status.'
                    }
                    if (!status?.has_versions) {
                        return 'Generate the widget first.'
                    }
                    if (!activeFrameNames.length) {
                        return 'This widget does not use notebook data.'
                    }
                    if (isDataChainRunning || notebookIsBusy) {
                        return 'Another notebook operation is running.'
                    }
                    return null
                },
            ],
            sourceImprovementDisabledReason: [
                (selectors) => [
                    selectors.generationRequestLoading,
                    selectors.isWorking,
                    selectors.selectedVersionId,
                    selectors.selectedVersion,
                    selectors.sourceChangePrompt,
                    selectors.sourceError,
                    selectors.sourceLoading,
                    selectors.sourceVersionId,
                    selectors.status,
                ],
                (
                    generationRequestLoading,
                    isWorking,
                    selectedVersionId,
                    selectedVersion,
                    sourceChangePrompt,
                    sourceError,
                    sourceLoading,
                    sourceVersionId,
                    status
                ): string | null => {
                    if (selectedVersionId !== status?.current_version_id) {
                        return 'Restore this version before building changes.'
                    }
                    if (!sourceChangePrompt.trim()) {
                        return 'Describe the changes you want.'
                    }
                    if (!selectedVersion || selectedVersion.id !== selectedVersionId) {
                        return 'Loading the widget version.'
                    }
                    if (!isWidgetModel(selectedVersion.model)) {
                        return 'This widget version uses an unavailable model.'
                    }
                    if (sourceError) {
                        return 'Reload the widget source first.'
                    }
                    if (sourceLoading || sourceVersionId !== selectedVersionId) {
                        return 'Loading the widget source.'
                    }
                    if (isWorking || generationRequestLoading) {
                        return 'Wait for widget generation to finish.'
                    }
                    return null
                },
            ],
        }),
        listeners(({ actions, values, props, cache }) => {
            const requestWithTimeout = async <T>(request: (signal: AbortSignal) => Promise<T>): Promise<T> => {
                const controller = new AbortController()
                const controllers = (cache.requestControllers ??= new Set<AbortController>()) as Set<AbortController>
                controllers.add(controller)
                const timeoutId = window.setTimeout(
                    () => controller.abort(new Error('The widget request timed out.')),
                    WIDGET_REQUEST_TIMEOUT_MS
                )
                try {
                    return await request(controller.signal)
                } finally {
                    window.clearTimeout(timeoutId)
                    controllers.delete(controller)
                }
            }

            const nextStatusRequestId = (): number => {
                const requestId = Number(cache.statusRequestId ?? 0) + 1
                cache.statusRequestId = requestId
                return requestId
            }

            const isCurrentStatusRequest = (requestId: number): boolean => requestId === cache.statusRequestId

            const invalidateStatusRequests = (): void => {
                nextStatusRequestId()
                actions.statusRequestFinished()
            }

            const loadStatusAfterMutationFailure = async (): Promise<WidgetStatusApi | null> => {
                if (!props.projectId || !isSafeWidgetNodeId(props.nodeId)) {
                    return null
                }
                try {
                    return await requestWithTimeout((signal) =>
                        notebooksWidgetStatus(String(props.projectId), props.notebookShortId, props.nodeId, { signal })
                    )
                } catch {
                    return null
                }
            }

            const scheduleStatusPoll = (): void => {
                cache.disposables.dispose('statusPoll')
                if (document.hidden) {
                    return
                }
                const attempt = Number(cache.statusPollAttempts ?? 0)
                const delay = Math.min(STATUS_POLL_INTERVAL_MS * 2 ** attempt, STATUS_POLL_MAX_INTERVAL_MS)
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
                cancelGeneration: async () => {
                    const generationId = values.status?.active_job?.id
                    if (
                        !props.isEditable ||
                        !generationId ||
                        !props.projectId ||
                        !isSafeWidgetNodeId(props.nodeId) ||
                        values.cancellationInFlight
                    ) {
                        return
                    }
                    actions.cancellationStarted()
                    try {
                        await requestWithTimeout((signal) =>
                            notebooksWidgetCancel(
                                String(props.projectId),
                                props.notebookShortId,
                                props.nodeId,
                                { generation_id: generationId },
                                { signal }
                            )
                        )
                        actions.generationCanceled()
                        actions.loadStatus()
                    } catch (error) {
                        // An unmount aborts in-flight requests; that is not a failure to recover from or report.
                        if (isAbortError(error)) {
                            return
                        }
                        const recoveredStatus = isAmbiguousMutationError(error)
                            ? await loadStatusAfterMutationFailure()
                            : null
                        if (recoveredStatus && recoveredStatus.active_job?.id !== generationId) {
                            actions.generationCanceled()
                            invalidateStatusRequests()
                            if (recoveredStatus) {
                                actions.statusReceived(recoveredStatus)
                            }
                            return
                        }
                        const message = errorMessage(error)
                        posthog.captureException(error instanceof Error ? error : new Error(message), {
                            action: 'cancel notebook widget generation',
                        })
                        actions.cancellationFailed(message)
                    }
                },
                generateWidget: async ({ prompt, model, operation, expectedCurrentVersionId }) => {
                    if (!props.isEditable || values.generationRequestLoading || values.isWorking) {
                        return
                    }
                    if (!isSafeWidgetNodeId(props.nodeId)) {
                        actions.generationFailed('This widget has an invalid identifier.')
                        return
                    }
                    if (!props.projectId) {
                        actions.generationFailed('The current project is unavailable. Refresh and try again.')
                        return
                    }
                    const submittedPrompt = prompt.trim() || (operation === 'initial' ? DEFAULT_WIDGET_PROMPT : '')
                    if (!submittedPrompt) {
                        actions.generationFailed(
                            operation === 'improve'
                                ? 'Describe the change you want to make.'
                                : 'Add instructions before generating the widget.'
                        )
                        return
                    }
                    const maxPromptLength =
                        operation === 'regenerate' ? MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH : MAX_WIDGET_PROMPT_LENGTH
                    if (submittedPrompt.length > maxPromptLength) {
                        actions.generationFailed(
                            `Keep widget instructions to ${maxPromptLength.toLocaleString()} characters or fewer.`
                        )
                        return
                    }
                    if (operation === 'improve' && !expectedCurrentVersionId) {
                        actions.generationFailed('Reload the widget before improving it.')
                        return
                    }
                    actions.generationRequestStarted()
                    invalidateStatusRequests()
                    const generationId = uuidv4()
                    let aborted = false
                    try {
                        const requestGeneration = async (): Promise<WidgetStatusApi> =>
                            await requestWithTimeout((signal) =>
                                notebooksWidgetGenerate(
                                    String(props.projectId),
                                    props.notebookShortId,
                                    props.nodeId,
                                    {
                                        prompt: submittedPrompt,
                                        generation_id: generationId,
                                        model,
                                        generation_operation: operation,
                                        expected_current_version_id: expectedCurrentVersionId,
                                    },
                                    { signal }
                                )
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
                        actions.closeSourceModal()
                        invalidateStatusRequests()
                        actions.statusReceived(queuedStatus)
                    } catch (error) {
                        // An unmount aborts in-flight requests; that is not a failure to recover from or report.
                        if (isAbortError(error)) {
                            aborted = true
                            return
                        }
                        const recoveredStatus = isAmbiguousMutationError(error)
                            ? await loadStatusAfterMutationFailure()
                            : null
                        if (recoveredStatus?.active_job?.id === generationId) {
                            actions.closeGenerationModal()
                            actions.closeSourceModal()
                            invalidateStatusRequests()
                            actions.statusReceived(recoveredStatus)
                            return
                        }
                        const message = errorMessage(error)
                        posthog.captureException(error instanceof Error ? error : new Error(message), {
                            action: 'generate notebook widget',
                        })
                        actions.generationFailed(message)
                    } finally {
                        if (!aborted) {
                            actions.generationRequestFinished()
                        }
                    }
                },
                loadMoreVersions: () => {
                    if (values.versionsNextOffset !== null) {
                        actions.loadVersions(false)
                    }
                },
                improveSource: () => {
                    if (values.sourceImprovementDisabledReason) {
                        return
                    }
                    if (values.selectedVersion && isWidgetModel(values.selectedVersion.model)) {
                        actions.generateWidget(
                            values.sourceChangePrompt,
                            values.selectedVersion.model,
                            'improve',
                            values.sourceVersionId ?? undefined
                        )
                    }
                },
                loadSource: async () => {
                    if (!props.projectId) {
                        actions.sourceFailed('The current project is unavailable.')
                        return
                    }
                    if (!isSafeWidgetNodeId(props.nodeId)) {
                        actions.sourceFailed('This widget has an invalid identifier.')
                        return
                    }
                    const requestedVersionId = values.selectedVersionId
                    const requestId = Number(cache.sourceRequestId ?? 0) + 1
                    cache.sourceRequestId = requestId
                    try {
                        const result = await requestWithTimeout((signal) =>
                            notebooksWidgetSource(
                                String(props.projectId),
                                props.notebookShortId,
                                props.nodeId,
                                { version_id: requestedVersionId ?? undefined },
                                { signal }
                            )
                        )
                        if (requestId === cache.sourceRequestId && requestedVersionId === values.selectedVersionId) {
                            actions.sourceReceived(result.source, requestedVersionId)
                        }
                    } catch (error) {
                        if (requestId === cache.sourceRequestId) {
                            actions.sourceFailed(errorMessage(error))
                        }
                    }
                },
                refreshData: async () => {
                    if (!props.projectId) {
                        actions.dataRefreshFinished()
                        actions.statusFailed('The current project is unavailable. Refresh and try again.')
                        return
                    }
                    if (!isSafeWidgetNodeId(props.nodeId)) {
                        actions.dataRefreshFinished()
                        actions.statusFailed('This widget has an invalid identifier.')
                        return
                    }
                    if (cache.refreshDataRequestInFlight) {
                        return
                    }
                    cache.refreshDataRequestInFlight = true
                    const requestId = nextStatusRequestId()
                    const requestedVersionId = values.selectedVersionId
                    actions.statusRequestStarted()
                    try {
                        const refreshedStatus = await requestWithTimeout((signal) =>
                            notebooksWidgetStatus(String(props.projectId), props.notebookShortId, props.nodeId, {
                                signal,
                            })
                        )
                        if (isCurrentStatusRequest(requestId)) {
                            actions.statusReceived(refreshedStatus)
                        }
                        if (requestedVersionId && requestedVersionId !== refreshedStatus.current_version_id) {
                            const selectedIndex = values.versions.findIndex(({ id }) => id === requestedVersionId)
                            const offset =
                                Math.floor(Math.max(selectedIndex, 0) / VERSION_PAGE_SIZE) * VERSION_PAGE_SIZE
                            const page = await requestWithTimeout((signal) =>
                                notebooksWidgetVersions(
                                    String(props.projectId),
                                    props.notebookShortId,
                                    props.nodeId,
                                    { offset, limit: VERSION_PAGE_SIZE },
                                    { signal }
                                )
                            )
                            const refreshedVersion = page.results.find(({ id }) => id === requestedVersionId)
                            if (!refreshedVersion) {
                                throw new Error('The selected widget version is no longer available.')
                            }
                            actions.versionRefreshed(refreshedVersion)
                        }
                        actions.artifactRefreshReady()
                    } catch (error) {
                        actions.dataRefreshFinished()
                        if (isCurrentStatusRequest(requestId)) {
                            actions.statusFailed(errorMessage(error))
                        }
                    } finally {
                        cache.refreshDataRequestInFlight = false
                        if (isCurrentStatusRequest(requestId)) {
                            actions.statusRequestFinished()
                        }
                    }
                },
                loadStatus: async () => {
                    if (!props.projectId) {
                        return
                    }
                    if (!isSafeWidgetNodeId(props.nodeId)) {
                        actions.statusFailed('This widget has an invalid identifier.')
                        return
                    }
                    const requestId = nextStatusRequestId()
                    actions.statusRequestStarted()
                    try {
                        const loadedStatus = await requestWithTimeout((signal) =>
                            notebooksWidgetStatus(String(props.projectId), props.notebookShortId, props.nodeId, {
                                signal,
                            })
                        )
                        if (isCurrentStatusRequest(requestId)) {
                            actions.statusReceived(loadedStatus)
                        }
                    } catch (error) {
                        if (isCurrentStatusRequest(requestId)) {
                            actions.statusFailed(errorMessage(error))
                        }
                    } finally {
                        if (isCurrentStatusRequest(requestId)) {
                            actions.statusRequestFinished()
                        }
                    }
                },
                loadVersions: async ({ reset }) => {
                    if (!props.projectId) {
                        actions.versionsFailed('The current project is unavailable.')
                        return
                    }
                    if (!isSafeWidgetNodeId(props.nodeId)) {
                        actions.versionsFailed('This widget has an invalid identifier.')
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
                        const page = await requestWithTimeout((signal) =>
                            notebooksWidgetVersions(
                                String(props.projectId),
                                props.notebookShortId,
                                props.nodeId,
                                { offset, limit: VERSION_PAGE_SIZE },
                                { signal }
                            )
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
                openGenerationModal: ({ operation }) => {
                    if (operation === 'regenerate' && values.status?.has_versions && !values.selectedVersion) {
                        cache.regenerationDraftVersionId = values.selectedVersionId
                        actions.loadVersions(true)
                    } else {
                        cache.regenerationDraftVersionId = null
                    }
                    actions.setGenerationDraftPrompt(
                        operation === 'regenerate'
                            ? values.selectedVersion?.effective_prompt ||
                                  (values.status?.has_versions ? '' : props.prompt)
                            : ''
                    )
                    actions.setGenerationDraftModel(
                        isWidgetModel(values.selectedVersion?.model) ? values.selectedVersion.model : props.model
                    )
                },
                openSourceModal: () => {
                    actions.loadStatus()
                    if (values.status?.has_versions && !values.selectedVersion) {
                        actions.loadVersions(true)
                    }
                    actions.loadSource()
                },
                runDataDependencies: () => {
                    if (values.dataRefreshInFlight || values.runDataDependenciesDisabledReason) {
                        return
                    }
                    const content = props.getContent()
                    const { missingFrameNames, nodeIds } = getWidgetDataDependencies(content, values.activeFrameNames)
                    if (missingFrameNames.length) {
                        const message =
                            'The widget expects notebook data that is no longer available. Restore the missing SQL or Python cell, or update the widget source.'
                        actions.setRuntimeError(message)
                        // The runtimeError banner only renders in the expanded preview, so a toast keeps
                        // the failure visible when the widget is collapsed or still behind the trust gate.
                        lemonToast.error(message)
                        return
                    }
                    if (!nodeIds.length) {
                        const message = 'No matching notebook data cells were found. Check the widget source.'
                        actions.setRuntimeError(message)
                        lemonToast.error(message)
                        return
                    }
                    actions.setRuntimeError(null)
                    cache.widgetDataRefreshRequested = true
                    actions.dataRefreshStarted()
                    actions.runWidgetDataChain(content, nodeIds)
                },
                restoreSelectedVersion: async () => {
                    const expectedCurrentVersionId = values.status?.current_version_id
                    if (
                        !props.isEditable ||
                        !props.projectId ||
                        !isSafeWidgetNodeId(props.nodeId) ||
                        !values.selectedVersionId ||
                        !expectedCurrentVersionId ||
                        values.selectedVersionId === expectedCurrentVersionId ||
                        values.restoreInFlight
                    ) {
                        return
                    }
                    actions.restoreStarted()
                    invalidateStatusRequests()
                    try {
                        const restoredStatus = await requestWithTimeout((signal) =>
                            notebooksWidgetRevert(
                                String(props.projectId),
                                props.notebookShortId,
                                props.nodeId,
                                {
                                    version_id: values.selectedVersionId!,
                                    expected_current_version_id: expectedCurrentVersionId,
                                },
                                { signal }
                            )
                        )
                        invalidateStatusRequests()
                        actions.statusReceived(restoredStatus)
                        if (restoredStatus.current_version_id) {
                            actions.selectVersion(restoredStatus.current_version_id)
                        }
                        actions.loadVersions(true)
                        actions.refreshData()
                    } catch (error) {
                        // An unmount aborts in-flight requests; that is not a failure to recover from or report.
                        if (isAbortError(error)) {
                            return
                        }
                        const recoveredStatus = isAmbiguousMutationError(error)
                            ? await loadStatusAfterMutationFailure()
                            : null
                        if (recoveredStatus) {
                            invalidateStatusRequests()
                            actions.statusReceived(recoveredStatus)
                            actions.loadVersions(true)
                        }
                        actions.restoreFailed(errorMessage(error))
                    }
                },
                selectVersion: () => {
                    if (values.sourceModalOpen) {
                        actions.loadSource()
                    }
                },
                statusReceived: ({ status }) => {
                    cache.disposables.dispose('statusPoll')
                    // A null -> id move (the first version appearing) must count as a change, so compare
                    // against undefined, which only holds before the first status arrives. Reload even when
                    // the list is empty, or a settings panel opened before generation keeps a stale history.
                    const currentVersionChanged = Boolean(
                        status.current_version_id &&
                        cache.currentVersionId !== undefined &&
                        cache.currentVersionId !== status.current_version_id
                    )
                    if (currentVersionChanged) {
                        actions.loadVersions(true)
                        cache.pendingCurrentVersionId = status.artifact_url ? null : status.current_version_id
                    }
                    if (
                        status.current_version_id &&
                        status.artifact_url &&
                        (currentVersionChanged || cache.pendingCurrentVersionId === status.current_version_id)
                    ) {
                        actions.selectVersion(status.current_version_id)
                        cache.pendingCurrentVersionId = null
                    }
                    cache.currentVersionId = status.current_version_id
                    if (shouldPoll(status)) {
                        cache.statusPollAttempts = Number(cache.statusPollAttempts ?? 0) + 1
                        scheduleStatusPoll()
                        const startedAtRaw = status.active_job?.started_at ?? status.active_job?.created_at
                        const startedAt = startedAtRaw
                            ? new Date(startedAtRaw).getTime()
                            : (cache.generationStartedAt ?? Date.now())
                        if (startedAt !== cache.generationStartedAt) {
                            startElapsedClock(startedAt)
                        }
                    } else {
                        cache.statusPollAttempts = 0
                        cache.disposables.dispose('elapsedClock')
                        cache.generationStartedAt = null
                    }
                },
                versionsReceived: () => {
                    if (
                        values.generationModalOperation !== 'regenerate' ||
                        !values.selectedVersion ||
                        values.selectedVersion.id !== cache.regenerationDraftVersionId
                    ) {
                        return
                    }
                    cache.regenerationDraftVersionId = null
                    actions.setGenerationDraftPrompt(values.selectedVersion.effective_prompt)
                    if (isWidgetModel(values.selectedVersion.model)) {
                        actions.setGenerationDraftModel(values.selectedVersion.model)
                    }
                },
                closeGenerationModal: () => {
                    cache.regenerationDraftVersionId = null
                },
                statusFailed: () => {
                    if (shouldPoll(values.status)) {
                        cache.statusPollAttempts = Number(cache.statusPollAttempts ?? 0) + 1
                        scheduleStatusPoll()
                    }
                },
                abortChain: ({ reason }) => {
                    if (!cache.widgetDataRefreshRequested) {
                        return
                    }
                    cache.widgetDataRefreshRequested = false
                    actions.setRuntimeError(
                        reason
                            ? `The connected data cell “${reason}” did not finish successfully. Open that cell, fix its error, then run the widget data cells again.`
                            : 'Some connected data cells are unavailable. Scroll through the notebook, then run the widget data cells again.'
                    )
                },
                dataRefreshStarted: () => {
                    cache.widgetDataRefreshRequested = true
                },
                widgetDataChainFinished: () => {
                    if (!values.dataRefreshInFlight) {
                        return
                    }
                    cache.widgetDataRefreshRequested = false
                    actions.dataRefreshFinished()
                    actions.refreshData()
                },
            }
        }),
        afterMount(({ actions, cache }) => {
            cache.disposables.add(
                () => {
                    const handleVisibilityChange = (): void => {
                        if (document.hidden) {
                            cache.disposables.dispose('statusPoll')
                        } else {
                            actions.loadStatus()
                        }
                    }
                    document.addEventListener('visibilitychange', handleVisibilityChange)
                    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
                },
                'visibilityChange',
                { pauseOnPageHidden: false }
            )
            actions.loadStatus()
        }),
        beforeUnmount(({ cache }) => {
            const controllers = cache.requestControllers as Set<AbortController> | undefined
            controllers?.forEach((controller) => controller.abort())
            controllers?.clear()
        }),
    ])

export const notebookNodeGeneratedWidgetSettingsLogic: LogicWrapper<notebookNodeGeneratedWidgetSettingsLogicType> =
    kea<notebookNodeGeneratedWidgetSettingsLogicType>([
        props({} as NotebookNodeGeneratedWidgetLogicProps),
        key((props) => `${props.projectId}-${props.notebookShortId}-${props.nodeId}`),
        path((key) => ['products', 'notebooks', 'notebookNodeGeneratedWidgetSettingsLogic', key]),
        connect((props: NotebookNodeGeneratedWidgetLogicProps) => ({
            actions: [notebookNodeGeneratedWidgetLogic(props), ['loadVersions']],
        })),
        afterMount(({ actions }) => {
            actions.loadVersions(true)
        }),
    ])
