import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { v4 as uuidv4 } from 'uuid'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import {
    reusableWidgetsDiscardVersion,
    reusableWidgetsGenerate,
    reusableWidgetsRetrieve,
    reusableWidgetsSaveVersion,
    reusableWidgetsSource,
    reusableWidgetsStatus,
} from 'products/notebooks/frontend/generated/api'
import type { ReusableWidgetDetailApi } from 'products/notebooks/frontend/generated/api.schemas'

import { DEFAULT_WIDGET_MODEL, isWidgetModel } from '../NotebookNodeGeneratedWidget/widgetModels'

export type ReusableWidgetLogicProps = {
    widgetId: string
}

export interface reusableWidgetLogicValues {
    artifactUnavailable: boolean
    changePrompt: string
    currentTeamId: number | null
    reusableWidget: ReusableWidgetDetailApi | null
    reusableWidgetError: string | null
    reusableWidgetLoading: boolean
    reviewError: string | null
    reviewResult: ReusableWidgetDetailApi | null
    reviewResultLoading: boolean
    runtimeError: string | null
    source: string | null
    sourceError: string | null
    sourceLoading: boolean
    sourceModalOpen: boolean
    updateError: string | null
    updateInFlight: boolean
}

export interface reusableWidgetLogicActions {
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
    updateFailed: (error: string) => { error: string }
    updateFinished: () => { value: true }
    updateReusableWidget: (operation?: 'improve' | 'regenerate') => { operation: 'improve' | 'regenerate' }
    updateStarted: () => { value: true }
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
        closeSourceModal: true,
        markArtifactUnavailable: true,
        openSourceModal: true,
        pollUpdate: true,
        setChangePrompt: (prompt: string) => ({ prompt }),
        setRuntimeError: (error: string | null) => ({ error }),
        updateFailed: (error: string) => ({ error }),
        updateFinished: true,
        updateReusableWidget: (operation: 'improve' | 'regenerate' = 'improve') => ({ operation }),
        updateStarted: true,
    }),
    reducers({
        artifactUnavailable: [
            false,
            {
                markArtifactUnavailable: () => true,
                loadReusableWidget: () => false,
                loadReusableWidgetSuccess: () => false,
            },
        ],
        changePrompt: ['', { setChangePrompt: (_, { prompt }) => prompt, updateFinished: () => '' }],
        reusableWidgetError: [
            null as string | null,
            {
                loadReusableWidget: () => null,
                loadReusableWidgetFailure: (_, { error }) => error,
            },
        ],
        runtimeError: [
            null as string | null,
            { setRuntimeError: (_, { error }) => error, loadReusableWidgetSuccess: () => null },
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
                saveVersionFailure: (_, { error }) => error,
                discardVersionFailure: (_, { error }) => error,
            },
        ],
        sourceModalOpen: [false, { openSourceModal: () => true, closeSourceModal: () => false }],
        updateError: [
            null as string | null,
            { updateStarted: () => null, updateFailed: (_, { error }) => error, updateFinished: () => null },
        ],
        updateInFlight: [false, { updateStarted: () => true, updateFailed: () => false, updateFinished: () => false }],
    }),
    loaders(({ props, values }) => ({
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
                loadSource: async () => {
                    if (!values.currentTeamId) {
                        throw new Error('Select a project to load this reusable widget.')
                    }
                    const versionId = values.reusableWidget?.pending_version?.id
                    const response = await reusableWidgetsSource(
                        String(values.currentTeamId),
                        props.widgetId,
                        versionId ? { version_id: versionId } : undefined
                    )
                    return response.source
                },
            },
        ],
        reviewResult: [
            null as ReusableWidgetDetailApi | null,
            {
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
    listeners(({ actions, cache, props, values }) => ({
        openSourceModal: actions.loadSource,
        loadReusableWidgetSuccess: ({ reusableWidget }) => {
            if (
                reusableWidget.pending_version &&
                reusableWidget.pending_version.build_status !== 'ready' &&
                reusableWidget.pending_version.build_status !== 'failed' &&
                !values.updateInFlight
            ) {
                actions.updateStarted()
                cache.disposables.add(() => {
                    const intervalId = window.setInterval(() => actions.pollUpdate(), 2_000)
                    return () => window.clearInterval(intervalId)
                }, 'widgetUpdatePoll')
                actions.pollUpdate()
            }
        },
        updateReusableWidget: async ({ operation }) => {
            const prompt = values.changePrompt.trim()
            if (!values.currentTeamId || !values.reusableWidget || !prompt || values.updateInFlight) {
                return
            }
            actions.updateStarted()
            cache.updateStartingVersion = values.reusableWidget.current_version.id
            try {
                await reusableWidgetsGenerate(String(values.currentTeamId), props.widgetId, {
                    prompt,
                    generation_id: uuidv4(),
                    model: isWidgetModel(values.reusableWidget.current_version.model)
                        ? values.reusableWidget.current_version.model
                        : DEFAULT_WIDGET_MODEL,
                    generation_operation: operation,
                    expected_current_version_id: values.reusableWidget.current_version.id,
                })
                cache.disposables.add(() => {
                    const intervalId = window.setInterval(() => actions.pollUpdate(), 2_000)
                    return () => window.clearInterval(intervalId)
                }, 'widgetUpdatePoll')
                actions.pollUpdate()
            } catch (error) {
                actions.updateFailed(error instanceof Error ? error.message : 'The widget update could not start.')
            }
        },
        pollUpdate: async () => {
            if (!values.currentTeamId || !values.updateInFlight) {
                cache.disposables.dispose('widgetUpdatePoll')
                return
            }
            try {
                const status = await reusableWidgetsStatus(String(values.currentTeamId), props.widgetId)
                if (
                    status.active_job ||
                    status.lifecycle_status === 'generating' ||
                    status.lifecycle_status === 'building'
                ) {
                    return
                }
                const reusableWidget = await reusableWidgetsRetrieve(String(values.currentTeamId), props.widgetId)
                actions.loadReusableWidgetSuccess(reusableWidget)
                if (reusableWidget.pending_version) {
                    if (
                        reusableWidget.pending_version.build_status !== 'ready' &&
                        reusableWidget.pending_version.build_status !== 'failed'
                    ) {
                        return
                    }
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
                if (
                    status.lifecycle_status === 'ready' &&
                    reusableWidget.current_version.id !== cache.updateStartingVersion
                ) {
                    actions.updateFinished()
                    lemonToast.success('Reusable widget updated')
                    return
                }
                actions.updateFailed(status.error_detail || 'The reusable widget could not be updated.')
            } catch (error) {
                cache.disposables.dispose('widgetUpdatePoll')
                actions.updateFailed(error instanceof Error ? error.message : 'The widget status could not be loaded.')
            }
        },
        saveVersionSuccess: ({ reviewResult }) => {
            actions.loadReusableWidgetSuccess(reviewResult)
            actions.closeSourceModal()
            lemonToast.success('Reusable widget version saved')
        },
        discardVersionSuccess: ({ reviewResult }) => {
            actions.loadReusableWidgetSuccess(reviewResult)
            actions.closeSourceModal()
            lemonToast.success('Draft discarded')
        },
    })),
    afterMount(({ actions }) => actions.loadReusableWidget()),
])
