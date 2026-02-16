import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'

import { WorkflowLogicProps, sanitizeWorkflow, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import type { HogflowTestResult } from '../steps/types'
import type { HogFlowAction } from '../types'
import type { hogFlowOutputMappingLogicType } from './hogFlowOutputMappingLogicType'
import { createExampleEvent, hogFlowEditorTestLogic } from './testing/hogFlowEditorTestLogic'

export type OutputMapping = { key: string; result_path: string; spread?: boolean | null }

export function normalizeOutputVariable(raw: HogFlowAction['output_variable']): OutputMapping[] {
    if (!raw) {
        return []
    }
    if (Array.isArray(raw)) {
        return raw.map((v) => ({ key: v.key, result_path: v.result_path || '', spread: v.spread }))
    }
    if (raw.key) {
        return [{ key: raw.key, result_path: raw.result_path || '', spread: raw.spread }]
    }
    return []
}

export const hogFlowOutputMappingLogic = kea<hogFlowOutputMappingLogicType>([
    path((key) => [
        'products',
        'workflows',
        'frontend',
        'Workflows',
        'hogflows',
        'panel',
        'hogFlowOutputMappingLogic',
        key,
    ]),
    props({} as WorkflowLogicProps),
    key((props) => props.id ?? 'new'),
    connect((props: WorkflowLogicProps) => ({
        values: [
            workflowLogic(props),
            ['workflow', 'hogFunctionTemplatesById'],
            hogFlowEditorLogic,
            ['selectedNode'],
            hogFlowEditorTestLogic(props),
            ['sampleGlobals', 'accumulatedVariables'],
        ],
    })),
    actions({
        setSelectedActionId: (actionId: string | null) => ({ actionId }),
        initMappings: (mappings: OutputMapping[]) => ({ mappings }),
        setMappings: (mappings: OutputMapping[]) => ({ mappings }),
        updateMappingResultPath: (index: number, path: string) => ({ index, path }),
        addMapping: true,
        removeMapping: (index: number) => ({ index }),
        selectPath: (path: string) => ({ path }),
        assignPendingPathToMapping: (index: number, path: string) => ({ index, path }),
        cancelPendingPath: true,
        runOutputTest: true,
        triggerShake: true,
        setTestLoading: (loading: boolean) => ({ loading }),
        setTestError: (error: string | null) => ({ error }),
        setTestResultData: (data: unknown | null) => ({ data }),
        setShakePickButton: (shake: boolean) => ({ shake }),
    }),
    reducers({
        selectedActionId: [
            null as string | null,
            {
                setSelectedActionId: (_, { actionId }) => actionId,
            },
        ],
        mappings: [
            [] as OutputMapping[],
            {
                setSelectedActionId: () => [],
                initMappings: (_, { mappings }) => mappings,
                setMappings: (_, { mappings }) => mappings,
                updateMappingResultPath: (state, { index, path }) => {
                    const updated = [...state]
                    updated[index] = { ...updated[index], result_path: path }
                    return updated
                },
                addMapping: (state) => [...state, { key: '', result_path: '' }],
                removeMapping: (state, { index }) => state.filter((_, i) => i !== index),
                assignPendingPathToMapping: (state) => state,
            },
        ],
        pendingPath: [
            null as string | null,
            {
                setSelectedActionId: () => null,
                selectPath: (_, { path }) => path,
                assignPendingPathToMapping: () => null,
                cancelPendingPath: () => null,
            },
        ],
        testLoading: [
            false,
            {
                setTestLoading: (_, { loading }) => loading,
            },
        ],
        testError: [
            null as string | null,
            {
                setSelectedActionId: () => null,
                setTestError: (_, { error }) => error,
            },
        ],
        testResultData: [
            null as unknown | null,
            {
                setSelectedActionId: () => null,
                setTestResultData: (_, { data }) => data,
            },
        ],
        shakePickButton: [
            false,
            {
                setShakePickButton: (_, { shake }) => shake,
            },
        ],
    }),
    selectors({
        selectedAction: [(s) => [s.selectedNode], (selectedNode) => selectedNode?.data ?? null],
    }),
    listeners(({ actions, values, props }) => {
        const persistMappings = (newMappings: OutputMapping[]): void => {
            const selectedNode = values.selectedNode
            if (!selectedNode) {
                return
            }
            const filtered = newMappings.filter((m) => m.key)
            const toOutput = (m: OutputMapping): Record<string, unknown> => ({
                key: m.key,
                result_path: m.result_path || null,
                ...(m.spread ? { spread: true } : {}),
            })
            const outputVariable =
                filtered.length === 0 ? null : filtered.length === 1 ? toOutput(filtered[0]) : filtered.map(toOutput)
            workflowLogic(props).actions.setWorkflowAction(selectedNode.data.id, {
                ...selectedNode.data,
                output_variable: outputVariable,
            } as HogFlowAction)
        }

        return {
            setSelectedActionId: () => {
                const selectedNode = values.selectedNode
                if (selectedNode) {
                    actions.initMappings(normalizeOutputVariable(selectedNode.data.output_variable))
                }
            },
            setMappings: ({ mappings }) => {
                persistMappings(mappings)
            },
            updateMappingResultPath: () => {
                persistMappings(values.mappings)
                actions.triggerShake()
            },
            addMapping: () => {
                persistMappings(values.mappings)
            },
            removeMapping: () => {
                persistMappings(values.mappings)
            },
            selectPath: ({ path }) => {
                if (values.mappings.length <= 1) {
                    if (values.mappings.length === 0) {
                        actions.setMappings([{ key: '', result_path: path }])
                    } else {
                        const updated = [...values.mappings]
                        updated[0] = { ...updated[0], result_path: path }
                        actions.setMappings(updated)
                    }
                }
                // If ≥2 mappings, pendingPath is already set by the reducer
            },
            assignPendingPathToMapping: ({ index, path }) => {
                const updated = [...values.mappings]
                updated[index] = { ...updated[index], result_path: path }
                actions.setMappings(updated)
            },
            triggerShake: () => {
                if (!values.shakePickButton) {
                    actions.setShakePickButton(true)
                    setTimeout(() => actions.setShakePickButton(false), 1000)
                }
            },
            runOutputTest: async () => {
                const { selectedNode, workflow, hogFunctionTemplatesById } = values
                if (!selectedNode || workflow.id === 'new') {
                    return
                }

                actions.setTestLoading(true)
                actions.setTestError(null)
                actions.setTestResultData(null)

                try {
                    const sampleGlobals = values.sampleGlobals ?? createExampleEvent(workflow.team_id, workflow.name)

                    const variableDefaults =
                        workflow.variables?.reduce(
                            (acc: Record<string, any>, v) => {
                                acc[v.key] = v.default
                                return acc
                            },
                            {} as Record<string, any>
                        ) ?? {}

                    const globals = {
                        ...sampleGlobals,
                        variables: {
                            ...variableDefaults,
                            ...values.accumulatedVariables,
                        },
                    }

                    const config = sanitizeWorkflow(JSON.parse(JSON.stringify(workflow)), hogFunctionTemplatesById)

                    const result: HogflowTestResult = await api.hogFlows.createTestInvocation(workflow.id, {
                        configuration: config,
                        globals,
                        mock_async_functions: false,
                        current_action_id: selectedNode.data.id,
                    })

                    if (result.execResult != null) {
                        actions.setTestResultData(result.execResult)
                    }

                    if (result.status === 'error') {
                        actions.setTestError(result.errors?.join(', ') || 'Test execution failed')
                    } else if (result.execResult == null) {
                        actions.setTestError('Test succeeded but no response data was returned.')
                    }
                } catch (e: any) {
                    if (e.data) {
                        actions.setTestError(JSON.stringify(e.data, null, 2))
                    } else {
                        actions.setTestError(e.detail || e.message || 'Failed to run test')
                    }
                } finally {
                    actions.setTestLoading(false)
                }
            },
        }
    }),
])
