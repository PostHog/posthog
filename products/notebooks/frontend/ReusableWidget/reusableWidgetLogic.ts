import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { v4 as uuidv4 } from 'uuid'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    reusableWidgetsDiscardVersion,
    reusableWidgetsGenerate,
    reusableWidgetsRetrieve,
    reusableWidgetsRestore,
    reusableWidgetsSaveVersion,
    reusableWidgetsSource,
    reusableWidgetsStatus,
    reusableWidgetsVersions,
} from 'products/notebooks/frontend/generated/api'
import type {
    ReusableWidgetDetailApi,
    ReusableWidgetVersionDetailApi,
    ReusableWidgetVersionPageApi,
} from 'products/notebooks/frontend/generated/api.schemas'

import { DEFAULT_WIDGET_MODEL, isWidgetModel, WidgetModel } from '../NotebookNodeGeneratedWidget/widgetModels'

export type ReusableWidgetLogicProps = {
    widgetId: string
}

export interface reusableWidgetLogicValues {
    demoDataModalOpen: boolean
    demoDataRevision: number
    artifactUnavailable: boolean
    changePrompt: string
    currentTeamId: number | null
    modelOverride: WidgetModel | null
    reusableWidget: ReusableWidgetDetailApi | null
    reusableWidgetError: string | null
    reusableWidgetLoading: boolean
    reviewError: string | null
    reviewResult: ReusableWidgetDetailApi | null
    reviewResultLoading: boolean
    selectedVersionId: string | null
    selectedVersion: ReusableWidgetVersionDetailApi | null
    versionHistory: ReusableWidgetVersionPageApi | null
    versionHistoryLoading: boolean
    versionHistoryError: string | null
    runtimeError: string | null
    source: string | null
    sourceError: string | null
    sourceLoading: boolean
    sourceModalOpen: boolean
    updateError: string | null
    updateInFlight: boolean
    updateModel: WidgetModel
    updateOperation: 'improve' | 'regenerate' | null
}

export interface reusableWidgetLogicActions {
    openDemoDataModal: () => { value: true }
    closeDemoDataModal: () => { value: true }
    demoDataSaved: () => { value: true }
    selectVersion: (versionId: string | null) => { versionId: string | null }
    loadVersionHistory: (offset?: number) => { offset: number }
    loadVersionHistorySuccess: (
        versionHistory: ReusableWidgetVersionPageApi,
        payload?: { offset: number }
    ) => { versionHistory: ReusableWidgetVersionPageApi; payload?: { offset: number } }
    loadVersionHistoryFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    restoreVersion: () => { value: true }
    restoreVersionSuccess: (
        reviewResult: ReusableWidgetDetailApi,
        payload?: { value: true }
    ) => { reviewResult: ReusableWidgetDetailApi; payload?: { value: true } }
    restoreVersionFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    closeSourceModal: () => { value: true }
    loadReusableWidget: () => { value: true }
    loadReusableWidgetFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadReusableWidgetSuccess: (
        reusableWidget: ReusableWidgetDetailApi,
        payload?: { value: true }
    ) => { reusableWidget: ReusableWidgetDetailApi; payload?: { value: true } }
    loadSource: () => { value: true }
    loadSourceFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    loadSourceSuccess: (source: string, payload?: { value: true }) => { source: string; payload?: { value: true } }
    markArtifactUnavailable: () => { value: true }
    openSourceModal: () => { value: true }
    setRuntimeError: (error: string | null) => { error: string | null }
    pollUpdate: () => { value: true }
    discardVersion: () => { value: true }
    discardVersionFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    discardVersionSuccess: (
        reviewResult: ReusableWidgetDetailApi,
        payload?: { value: true }
    ) => { reviewResult: ReusableWidgetDetailApi; payload?: { value: true } }
    saveVersion: () => { value: true }
    saveVersionFailure: (error: string, errorObject?: unknown) => { error: string; errorObject?: unknown }
    saveVersionSuccess: (
        reviewResult: ReusableWidgetDetailApi,
        payload?: { value: true }
    ) => { reviewResult: ReusableWidgetDetailApi; payload?: { value: true } }
    setChangePrompt: (prompt: string) => { prompt: string }
    setUpdateModel: (model: WidgetModel) => { model: WidgetModel }
    updateFailed: (error: string) => { error: string }
    updateFinished: () => { value: true }
    updateReusableWidget: (operation?: 'improve' | 'regenerate') => { operation: 'improve' | 'regenerate' }
    updateStarted: (operation?: 'improve' | 'regenerate') => { operation: 'improve' | 'regenerate' }
}

export interface reusableWidgetLogicMeta {
    key: string
}

export type reusableWidgetLogicType = MakeLogicType<
    reusableWidgetLogicValues,
    reusableWidgetLogicActions,
    ReusableWidgetLogicProps,
    reusableWidgetLogicMeta
>

export const reusableWidgetLogic = kea<reusableWidgetLogicType>([
    props({} as ReusableWidgetLogicProps),
    key((props) => props.widgetId),
    path((key) => ['products', 'notebooks', 'ReusableWidget', 'reusableWidgetLogic', key]),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        openDemoDataModal: true,
        closeDemoDataModal: true,
        demoDataSaved: true,
        loadVersionHistory: (offset: number = 0) => ({ offset }),
        selectVersion: (versionId: string | null) => ({ versionId }),
        closeSourceModal: true,
        markArtifactUnavailable: true,
        openSourceModal: true,
        pollUpdate: true,
        setChangePrompt: (prompt: string) => ({ prompt }),
        setUpdateModel: (model: WidgetModel) => ({ model }),
        setRuntimeError: (error: string | null) => ({ error }),
        updateFailed: (error: string) => ({ error }),
        updateFinished: true,
        updateReusableWidget: (operation: 'improve' | 'regenerate' = 'improve') => ({ operation }),
        updateStarted: (operation: 'improve' | 'regenerate' = 'improve') => ({ operation }),
    }),
    reducers({
        demoDataModalOpen: [
            false,
            { openDemoDataModal: () => true, closeDemoDataModal: () => false, selectVersion: () => false },
        ],
        demoDataRevision: [0, { demoDataSaved: (revision) => revision + 1 }],
        selectedVersionId: [
            null as string | null,
            {
                selectVersion: (_, { versionId }) => versionId,
                updateStarted: () => null,
                saveVersionSuccess: () => null,
                discardVersionSuccess: () => null,
                restoreVersionSuccess: () => null,
            },
        ],
        versionHistoryError: [
            null as string | null,
            {
                loadVersionHistory: () => null,
                loadVersionHistoryFailure: (_, { error }) => error,
            },
        ],
        artifactUnavailable: [
            false,
            {
                markArtifactUnavailable: () => true,
                loadReusableWidget: () => false,
                loadReusableWidgetSuccess: () => false,
                selectVersion: () => false,
            },
        ],
        changePrompt: ['', { setChangePrompt: (_, { prompt }) => prompt, updateFinished: () => '' }],
        modelOverride: [null as WidgetModel | null, { setUpdateModel: (_, { model }) => model }],
        reusableWidgetError: [
            null as string | null,
            {
                loadReusableWidget: () => null,
                loadReusableWidgetFailure: (_, { error }) => error,
            },
        ],
        runtimeError: [
            null as string | null,
            {
                setRuntimeError: (_, { error }) => error,
                loadReusableWidgetSuccess: () => null,
                selectVersion: () => null,
                demoDataSaved: () => null,
            },
        ],
        sourceError: [
            null as string | null,
            {
                loadSource: () => null,
                loadSourceFailure: (_, { error }) => error,
            },
        ],
        reviewError: [
            null as string | null,
            {
                saveVersion: () => null,
                discardVersion: () => null,
                restoreVersion: () => null,
                selectVersion: () => null,
                saveVersionFailure: (_, { error }) => error,
                discardVersionFailure: (_, { error }) => error,
                restoreVersionFailure: (_, { error }) => error,
            },
        ],
        sourceModalOpen: [false, { openSourceModal: () => true, closeSourceModal: () => false }],
        updateError: [
            null as string | null,
            { updateStarted: () => null, updateFailed: (_, { error }) => error, updateFinished: () => null },
        ],
        updateOperation: [
            null as 'improve' | 'regenerate' | null,
            {
                updateStarted: (_, { operation }) => operation,
                updateFailed: () => null,
                updateFinished: () => null,
            },
        ],
    }),
    loaders(({ props, values }) => ({
        versionHistory: [
            null as ReusableWidgetVersionPageApi | null,
            {
                loadVersionHistory: async ({ offset }, breakpoint) => {
                    if (!values.currentTeamId) {
                        throw new Error('Select a project to load version history.')
                    }
                    const page = await reusableWidgetsVersions(String(values.currentTeamId), props.widgetId, {
                        offset,
                    })
                    breakpoint()
                    return {
                        ...page,
                        results: offset ? [...(values.versionHistory?.results ?? []), ...page.results] : page.results,
                    }
                },
            },
        ],
        reusableWidget: [
            null as ReusableWidgetDetailApi | null,
            {
                loadReusableWidget: async () => {
                    if (!values.currentTeamId) {
                        throw new Error('Select a project to load this reusable widget.')
                    }
                    return await reusableWidgetsRetrieve(String(values.currentTeamId), props.widgetId)
                },
            },
        ],
        source: [
            null as string | null,
            {
                loadSource: async (_, breakpoint) => {
                    if (!values.currentTeamId) {
                        throw new Error('Select a project to load this reusable widget.')
                    }
                    const versionId = values.selectedVersion?.id
                    const response = await reusableWidgetsSource(
                        String(values.currentTeamId),
                        props.widgetId,
                        versionId ? { version_id: versionId } : undefined
                    )
                    breakpoint()
                    return response.source
                },
            },
        ],
        reviewResult: [
            null as ReusableWidgetDetailApi | null,
            {
                restoreVersion: async () => {
                    if (
                        !values.currentTeamId ||
                        !values.reusableWidget ||
                        !values.selectedVersion ||
                        values.updateInFlight ||
                        values.reusableWidget.pending_version
                    ) {
                        throw new Error('Finish the current update before making a version latest.')
                    }
                    return await reusableWidgetsRestore(String(values.currentTeamId), props.widgetId, {
                        version_id: values.selectedVersion.id,
                        expected_current_version_id: values.reusableWidget.current_version.id,
                    })
                },
                saveVersion: async () => {
                    if (!values.currentTeamId || !values.reusableWidget?.pending_version) {
                        throw new Error('Reload the reusable widget before saving this draft.')
                    }
                    return await reusableWidgetsSaveVersion(String(values.currentTeamId), props.widgetId, {
                        pending_version_id: values.reusableWidget.pending_version.id,
                        expected_current_version_id: values.reusableWidget.current_version.id,
                    })
                },
                discardVersion: async () => {
                    if (!values.currentTeamId || !values.reusableWidget?.pending_version) {
                        throw new Error('Reload the reusable widget before discarding this draft.')
                    }
                    return await reusableWidgetsDiscardVersion(String(values.currentTeamId), props.widgetId, {
                        pending_version_id: values.reusableWidget.pending_version.id,
                        expected_current_version_id: values.reusableWidget.current_version.id,
                    })
                },
            },
        ],
    })),
    selectors({
        selectedVersion: [
            (s) => [s.selectedVersionId, s.reusableWidget, s.versionHistory],
            (selectedVersionId, widget, history): ReusableWidgetVersionDetailApi | null => {
                if (!widget) {
                    return null
                }
                return (
                    [widget.pending_version, widget.current_version, ...(history?.results ?? [])].find(
                        (version) => version?.id === selectedVersionId
                    ) ??
                    widget.pending_version ??
                    widget.current_version
                )
            },
        ],
        updateInFlight: [(s) => [s.updateOperation], (operation): boolean => operation !== null],
        updateModel: [
            (s) => [s.modelOverride, s.reusableWidget],
            (modelOverride, reusableWidget): WidgetModel =>
                modelOverride ??
                (isWidgetModel(reusableWidget?.current_version.model)
                    ? reusableWidget.current_version.model
                    : DEFAULT_WIDGET_MODEL),
        ],
    }),
    listeners(({ actions, cache, props, values }) => ({
        openSourceModal: actions.loadSource,
        selectVersion: actions.closeSourceModal,
        loadReusableWidgetSuccess: ({ reusableWidget }) => {
            const historyKey = `${reusableWidget.current_version.id}:${reusableWidget.pending_version?.id ?? ''}`
            if (cache.historyKey !== historyKey) {
                cache.historyKey = historyKey
                actions.loadVersionHistory()
            }
            const previewVersion = reusableWidget.pending_version ?? reusableWidget.current_version
            if (!cache.initialStatusChecked) {
                cache.initialStatusChecked = true
                actions.pollUpdate()
            } else if (
                !values.updateInFlight &&
                (previewVersion.build_status === 'queued' || previewVersion.build_status === 'building')
            ) {
                actions.pollUpdate()
            }
        },
        updateStarted: () => {
            cache.disposables.add(() => {
                const intervalId = window.setInterval(() => actions.pollUpdate(), 2_000)
                return () => window.clearInterval(intervalId)
            }, 'widgetUpdatePoll')
        },
        updateFinished: () => {
            cache.waitingForDraft = false
            cache.disposables.dispose('widgetUpdatePoll')
        },
        updateFailed: () => {
            cache.waitingForDraft = false
            cache.disposables.dispose('widgetUpdatePoll')
        },
        updateReusableWidget: async ({ operation }, breakpoint) => {
            const prompt = values.changePrompt.trim()
            if (
                !values.currentTeamId ||
                !values.reusableWidget ||
                !prompt ||
                values.updateInFlight ||
                values.reviewResultLoading ||
                values.reusableWidget.pending_version
            ) {
                return
            }
            cache.generationStarting = true
            cache.waitingForDraft = true
            actions.updateStarted(operation)
            try {
                await reusableWidgetsGenerate(String(values.currentTeamId), props.widgetId, {
                    prompt,
                    generation_id: uuidv4(),
                    model: values.updateModel,
                    generation_operation: operation,
                    expected_current_version_id: values.reusableWidget.current_version.id,
                })
                breakpoint()
                cache.generationStarting = false
                actions.pollUpdate()
            } catch (error) {
                breakpoint()
                cache.generationStarting = false
                actions.updateFailed(error instanceof Error ? error.message : 'The widget update could not start.')
            }
        },
        pollUpdate: async (_, breakpoint) => {
            if (!values.currentTeamId || cache.generationStarting) {
                return
            }
            try {
                const status = await reusableWidgetsStatus(String(values.currentTeamId), props.widgetId)
                breakpoint()
                if (cache.generationStarting) {
                    return
                }
                if (
                    status.active_job ||
                    status.lifecycle_status === 'generating' ||
                    status.lifecycle_status === 'building'
                ) {
                    if (status.active_job || status.lifecycle_status === 'generating') {
                        cache.waitingForDraft = true
                    }
                    if (!values.updateInFlight) {
                        actions.updateStarted()
                    }
                    return
                }
                if (status.lifecycle_status === 'failed') {
                    actions.updateFailed(status.error_detail || 'The reusable widget could not be updated.')
                    return
                }
                if (!values.updateInFlight) {
                    return
                }
                const reusableWidget = await reusableWidgetsRetrieve(String(values.currentTeamId), props.widgetId)
                breakpoint()
                actions.loadReusableWidgetSuccess(reusableWidget)
                const previewVersion = reusableWidget.pending_version ?? reusableWidget.current_version
                if (previewVersion.build_status === 'queued' || previewVersion.build_status === 'building') {
                    return
                }
                if (reusableWidget.pending_version) {
                    cache.disposables.dispose('widgetUpdatePoll')
                    if (
                        reusableWidget.pending_version.build_status === 'ready' &&
                        reusableWidget.pending_version.artifact_url
                    ) {
                        actions.updateFinished()
                        lemonToast.success('Draft ready to review')
                        return
                    }
                    actions.updateFailed('The reusable widget draft could not be built.')
                    return
                }
                cache.disposables.dispose('widgetUpdatePoll')
                if (!cache.waitingForDraft && previewVersion.build_status === 'ready' && previewVersion.artifact_url) {
                    actions.updateFinished()
                    lemonToast.success('Reusable widget updated')
                    return
                }
                actions.updateFailed(status.error_detail || 'The reusable widget could not be updated.')
            } catch (error) {
                breakpoint()
                cache.disposables.dispose('widgetUpdatePoll')
                actions.updateFailed(error instanceof Error ? error.message : 'The widget status could not be loaded.')
            }
        },
        saveVersionSuccess: ({ reviewResult }) => {
            actions.loadReusableWidgetSuccess(reviewResult)
            actions.closeSourceModal()
            lemonToast.success('Reusable widget version saved')
        },
        restoreVersionSuccess: ({ reviewResult }) => {
            actions.loadReusableWidgetSuccess(reviewResult)
            actions.closeSourceModal()
            lemonToast.success(`Version ${reviewResult.current_version.version} is now the latest`)
        },
        discardVersionSuccess: ({ reviewResult }) => {
            actions.loadReusableWidgetSuccess(reviewResult)
            actions.closeSourceModal()
            lemonToast.success('Draft discarded')
        },
    })),
    afterMount(({ actions }) => actions.loadReusableWidget()),
])
