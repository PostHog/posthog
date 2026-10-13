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

import { LemonDialog } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { reusableWidgetsDemoFrame, reusableWidgetsUpdateDemoData } from '../generated/api'
import type { ReusableWidgetVersionDetailApi, WidgetFrameApi } from '../generated/api.schemas'
import { demoRowsAsJSON, parseDemoRows } from './reusableWidgetDemoData'

export interface ReusableWidgetDemoDataLogicProps {
    projectId: number
    widgetId: string
    version: ReusableWidgetVersionDetailApi
    canEdit: boolean
    onClose: () => void
    onSaved: () => void
}

export interface reusableWidgetDemoDataLogicValues {
    demoFrame: WidgetFrameApi | null
    demoFrameLoading: boolean
    loadError: string | null
    savedFrame: WidgetFrameApi | null
    savedFrameLoading: boolean
    saveError: string | null
    selectedInput: string
    editing: boolean
    draftJSON: string
    validation: { rows: WidgetFrameApi['rows']; error: string | null }
    hasChanges: boolean
}

export interface reusableWidgetDemoDataLogicActions {
    selectInput: (name: string) => { name: string }
    startEditing: () => { value: true }
    cancelEditing: () => { value: true }
    setDraftJSON: (text: string) => { text: string }
    requestClose: () => { value: true }
    loadDemoFrame: () => { value: true }
    loadDemoFrameSuccess: (demoFrame: WidgetFrameApi) => { demoFrame: WidgetFrameApi }
    loadDemoFrameFailure: (error: string) => { error: string }
    saveDemoData: () => { value: true }
    saveDemoDataSuccess: (savedFrame: WidgetFrameApi) => { savedFrame: WidgetFrameApi }
    saveDemoDataFailure: (error: string) => { error: string }
}

export type reusableWidgetDemoDataLogicType = MakeLogicType<
    reusableWidgetDemoDataLogicValues,
    reusableWidgetDemoDataLogicActions,
    ReusableWidgetDemoDataLogicProps,
    { key: string }
>

export const reusableWidgetDemoDataLogic: LogicWrapper<reusableWidgetDemoDataLogicType> =
    kea<reusableWidgetDemoDataLogicType>([
        props({} as ReusableWidgetDemoDataLogicProps),
        key((props) => `${props.widgetId}:${props.version.id}`),
        path((key) => ['products', 'notebooks', 'ReusableWidget', 'reusableWidgetDemoDataLogic', key]),
        actions({
            selectInput: (name: string) => ({ name }),
            startEditing: true,
            cancelEditing: true,
            setDraftJSON: (text: string) => ({ text }),
            requestClose: true,
        }),
        loaders(({ props, values }) => ({
            demoFrame: [
                null as WidgetFrameApi | null,
                {
                    loadDemoFrame: async (_, breakpoint) => {
                        const input = props.version.input_contract.find((input) => input.slot === values.selectedInput)
                        if (!input) {
                            throw new Error('Select an input to view its demo data.')
                        }
                        try {
                            const frame = await reusableWidgetsDemoFrame(
                                String(props.projectId),
                                props.widgetId,
                                input.slot,
                                {
                                    version_id: props.version.id,
                                }
                            )
                            breakpoint()
                            return frame
                        } catch (error) {
                            breakpoint()
                            if (
                                !(error instanceof ApiError) ||
                                error.status !== 404 ||
                                error.code !== 'frame_not_found'
                            ) {
                                throw error
                            }
                            return {
                                name: input.slot,
                                runId: props.version.id,
                                columns: input.columns ?? [],
                                rows: [],
                                totalRowCount: 0,
                                includedRowCount: 0,
                                offset: 0,
                                nextOffset: null,
                                truncated: false,
                            }
                        }
                    },
                },
            ],
            savedFrame: [
                null as WidgetFrameApi | null,
                {
                    saveDemoData: async () => {
                        if (!props.canEdit || !values.demoFrame || values.validation.error) {
                            throw new Error(
                                values.validation.error || 'Select the latest version or its draft to edit demo data.'
                            )
                        }
                        return await reusableWidgetsUpdateDemoData(String(props.projectId), props.widgetId, {
                            version_id: props.version.id,
                            frame_name: values.selectedInput,
                            rows: values.validation.rows,
                        })
                    },
                },
            ],
        })),
        reducers(({ props }) => ({
            selectedInput: [props.version.input_contract[0]?.slot ?? '', { selectInput: (_, { name }) => name }],
            editing: [
                false,
                { startEditing: () => true, cancelEditing: () => false, saveDemoDataSuccess: () => false },
            ],
            draftJSON: ['', { setDraftJSON: (_, { text }) => text }],
            loadError: [
                null as string | null,
                { loadDemoFrame: () => null, loadDemoFrameFailure: (_, { error }) => error },
            ],
            saveError: [
                null as string | null,
                {
                    saveDemoData: () => null,
                    saveDemoDataFailure: (_, { error }) => error,
                    setDraftJSON: () => null,
                    cancelEditing: () => null,
                },
            ],
        })),
        selectors({
            validation: [
                (s) => [s.draftJSON, s.demoFrame],
                (text, frame): reusableWidgetDemoDataLogicValues['validation'] => {
                    try {
                        return { rows: parseDemoRows(text, frame?.columns ?? []), error: null }
                    } catch (error) {
                        return { rows: [], error: error instanceof Error ? error.message : 'Check the demo rows.' }
                    }
                },
            ],
            hasChanges: [
                (s) => [s.editing, s.draftJSON, s.demoFrame],
                (editing, text, frame): boolean => editing && !!frame && text !== demoRowsAsJSON(frame),
            ],
        }),
        listeners(({ actions, props, values }) => ({
            selectInput: actions.loadDemoFrame,
            startEditing: () => {
                if (values.demoFrame) {
                    actions.setDraftJSON(demoRowsAsJSON(values.demoFrame))
                }
            },
            saveDemoDataSuccess: ({ savedFrame }) => {
                actions.loadDemoFrameSuccess(savedFrame)
                props.onSaved()
                lemonToast.success('Demo data saved')
            },
            requestClose: () => {
                if (values.savedFrameLoading) {
                    return
                }
                if (values.hasChanges) {
                    LemonDialog.open({
                        title: 'Discard demo data edits?',
                        description: 'Your saved demo data will stay unchanged.',
                        primaryButton: { children: 'Discard edits', status: 'danger', onClick: props.onClose },
                        secondaryButton: { children: 'Keep editing' },
                    })
                } else {
                    props.onClose()
                }
            },
        })),
        afterMount(({ actions, values }) => {
            if (values.selectedInput) {
                actions.loadDemoFrame()
            }
        }),
    ])
