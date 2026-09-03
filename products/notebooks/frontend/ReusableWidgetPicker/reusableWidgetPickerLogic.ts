import { MakeLogicType, actions, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { collectNotebookFrameNodes } from 'scenes/notebooks/Nodes/notebookNodeContent'

import { notebooksWidgetAttach, reusableWidgetsRetrieve } from 'products/notebooks/frontend/generated/api'
import type { ReusableWidgetDetailApi, WidgetStatusApi } from 'products/notebooks/frontend/generated/api.schemas'

import { isSafeWidgetNodeId } from '../NotebookNodeGeneratedWidget/notebookNodeGeneratedWidgetLogic'

export type ReusableWidgetDraftBinding = {
    source: string
    hog: string
}

export type ReusableWidgetPickerLogicProps = {
    projectId: number | null
    notebookShortId: string
    nodeId: string
    getContent: () => JSONContent | null
    onAttached: (
        widget: ReusableWidgetDetailApi,
        status: WidgetStatusApi,
        bindings: Record<string, ReusableWidgetDraftBinding>
    ) => void
}

export interface reusableWidgetPickerLogicValues {
    attachError: string | null
    attachInFlight: boolean
    bindings: Record<string, ReusableWidgetDraftBinding>
    pickerOpen: boolean
    selectedWidget: ReusableWidgetDetailApi | null
    selectedWidgetError: string | null
    selectedWidgetLoading: boolean
}

export interface reusableWidgetPickerLogicActions {
    attachReusableWidget: () => { value: true }
    attachFailed: (error: string) => { error: string }
    attachFinished: () => { value: true }
    attachStarted: () => { value: true }
    closePicker: () => { value: true }
    openPicker: () => { value: true }
    selectReusableWidget: (widgetId: string) => { widgetId: string }
    selectedWidgetFailed: (error: string) => { error: string }
    selectedWidgetReceived: (
        widget: ReusableWidgetDetailApi,
        bindings: Record<string, ReusableWidgetDraftBinding>
    ) => { widget: ReusableWidgetDetailApi; bindings: Record<string, ReusableWidgetDraftBinding> }
    setBindingHog: (slot: string, hog: string) => { slot: string; hog: string }
    setBindingSource: (slot: string, source: string) => { slot: string; source: string }
    showCatalog: () => { value: true }
}

export interface reusableWidgetPickerLogicMeta {
    key: string
}

export type reusableWidgetPickerLogicType = MakeLogicType<
    reusableWidgetPickerLogicValues,
    reusableWidgetPickerLogicActions,
    ReusableWidgetPickerLogicProps,
    reusableWidgetPickerLogicMeta
>

function messageForError(error: unknown): string {
    return error instanceof Error ? error.message : 'The reusable widget request failed.'
}

export const reusableWidgetPickerLogic = kea<reusableWidgetPickerLogicType>([
    props({} as ReusableWidgetPickerLogicProps),
    key((props) => `${props.projectId}-${props.notebookShortId}-${props.nodeId}`),
    path((key) => ['products', 'notebooks', 'ReusableWidgetPicker', 'reusableWidgetPickerLogic', key]),
    actions({
        attachReusableWidget: true,
        attachFailed: (error: string) => ({ error }),
        attachFinished: true,
        attachStarted: true,
        closePicker: true,
        openPicker: true,
        selectReusableWidget: (widgetId: string) => ({ widgetId }),
        selectedWidgetFailed: (error: string) => ({ error }),
        selectedWidgetReceived: (
            widget: ReusableWidgetDetailApi,
            bindings: Record<string, ReusableWidgetDraftBinding>
        ) => ({ widget, bindings }),
        setBindingHog: (slot: string, hog: string) => ({ slot, hog }),
        setBindingSource: (slot: string, source: string) => ({ slot, source }),
        showCatalog: true,
    }),
    reducers({
        attachError: [
            null as string | null,
            { attachStarted: () => null, attachFailed: (_, { error }) => error, closePicker: () => null },
        ],
        attachInFlight: [false, { attachStarted: () => true, attachFailed: () => false, attachFinished: () => false }],
        bindings: [
            {} as Record<string, ReusableWidgetDraftBinding>,
            {
                selectedWidgetReceived: (_, { bindings }) => bindings,
                setBindingHog: (state, { slot, hog }) => ({ ...state, [slot]: { ...state[slot], hog } }),
                setBindingSource: (state, { slot, source }) => ({ ...state, [slot]: { ...state[slot], source } }),
                showCatalog: () => ({}),
            },
        ],
        pickerOpen: [false, { openPicker: () => true, closePicker: () => false }],
        selectedWidget: [
            null as ReusableWidgetDetailApi | null,
            { selectedWidgetReceived: (_, { widget }) => widget, showCatalog: () => null, closePicker: () => null },
        ],
        selectedWidgetError: [
            null as string | null,
            {
                selectReusableWidget: () => null,
                selectedWidgetReceived: () => null,
                selectedWidgetFailed: (_, { error }) => error,
                showCatalog: () => null,
            },
        ],
        selectedWidgetLoading: [
            false,
            {
                selectReusableWidget: () => true,
                selectedWidgetReceived: () => false,
                selectedWidgetFailed: () => false,
                showCatalog: () => false,
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        selectReusableWidget: async ({ widgetId }) => {
            if (!props.projectId) {
                actions.selectedWidgetFailed('The current project is unavailable.')
                return
            }
            try {
                const widget = await reusableWidgetsRetrieve(String(props.projectId), widgetId)
                const frames = collectNotebookFrameNodes(props.getContent()).filter((frame) => frame.hasRun)
                const bindings = Object.fromEntries(
                    widget.current_version.frame_names.map((slot, index) => [
                        slot,
                        {
                            source: frames.find((frame) => frame.name === slot)?.name ?? frames[index]?.name ?? '',
                            hog: '',
                        },
                    ])
                )
                actions.selectedWidgetReceived(widget, bindings)
            } catch (error) {
                actions.selectedWidgetFailed(messageForError(error))
            }
        },
        attachReusableWidget: async () => {
            if (
                !props.projectId ||
                !values.selectedWidget ||
                values.attachInFlight ||
                !isSafeWidgetNodeId(props.nodeId)
            ) {
                return
            }
            const missingSlot = values.selectedWidget.current_version.frame_names.find(
                (slot) => !values.bindings[slot]?.source
            )
            if (missingSlot) {
                actions.attachFailed(`Choose a dataframe for "${missingSlot}".`)
                return
            }
            actions.attachStarted()
            try {
                const inputBindings = Object.fromEntries(
                    await Promise.all(
                        Object.entries(values.bindings).map(async ([slot, binding]) => {
                            const hog = binding.hog.trim()
                            const bytecode = hog ? (await api.hog.create(hog)).bytecode : undefined
                            return [slot, { source: binding.source, hog: hog || undefined, bytecode }]
                        })
                    )
                )
                const status = await notebooksWidgetAttach(
                    String(props.projectId),
                    props.notebookShortId,
                    props.nodeId,
                    {
                        widget_id: values.selectedWidget.id,
                        version_id: null,
                        input_bindings: inputBindings,
                    }
                )
                props.onAttached(values.selectedWidget, status, values.bindings)
                actions.closePicker()
            } catch (error) {
                actions.attachFailed(messageForError(error))
            } finally {
                actions.attachFinished()
            }
        },
    })),
])
