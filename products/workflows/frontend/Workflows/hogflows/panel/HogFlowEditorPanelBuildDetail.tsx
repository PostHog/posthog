import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'

import { IconExternal, IconPlay, IconPlus, IconX } from '@posthog/icons'
import {
    LemonBadge,
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonInput,
    LemonLabel,
    LemonSelect,
} from '@posthog/lemon-ui'

import api from 'lib/api'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { urls } from 'scenes/urls'

import { CategorySelect } from 'products/workflows/frontend/OptOuts/CategorySelect'

import { sanitizeWorkflow } from '../../workflowLogic'
import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { isOptOutEligibleAction } from '../steps/types'
import type { HogflowTestResult } from '../steps/types'
import type { HogFlowAction } from '../types'
import { OutputTestResultTree } from './OutputTestResultTree'
import { createExampleEvent, hogFlowEditorTestLogic } from './testing/hogFlowEditorTestLogic'

type OutputMapping = { key: string; result_path: string }

function normalizeOutputVariable(raw: HogFlowAction['output_variable']): OutputMapping[] {
    if (!raw) {
        return []
    }
    if (Array.isArray(raw)) {
        return raw.map((v) => ({ key: v.key, result_path: v.result_path || '' }))
    }
    if (raw.key) {
        return [{ key: raw.key, result_path: raw.result_path || '' }]
    }
    return []
}

export function HogFlowEditorPanelBuildDetail(): JSX.Element | null {
    const { selectedNode, workflow, categories, categoriesLoading, hogFunctionTemplatesById } =
        useValues(hogFlowEditorLogic)
    const { setWorkflowAction, setMode } = useActions(hogFlowEditorLogic)

    const [mappings, setMappingsState] = useState<OutputMapping[]>(() =>
        normalizeOutputVariable(selectedNode?.data.output_variable)
    )
    // Path clicked in the response tree that's waiting for the user to pick a target variable
    const [pendingPath, setPendingPath] = useState<string | null>(null)
    const assignToRef = useRef<HTMLDivElement>(null)

    // Track which node we're currently editing to reset state on node switch
    const currentNodeId = useRef(selectedNode?.data.id)

    // Sync local state when the selected node changes
    useEffect(() => {
        if (selectedNode?.data.id !== currentNodeId.current) {
            currentNodeId.current = selectedNode?.data.id
            setMappingsState(normalizeOutputVariable(selectedNode?.data.output_variable))
            setPendingPath(null)
        }
    }, [selectedNode?.data.id, selectedNode?.data.output_variable])

    // Persist mappings back to the workflow action
    const persistMappings = useCallback(
        (newMappings: OutputMapping[]) => {
            if (!selectedNode) {
                return
            }
            const filtered = newMappings.filter((m) => m.key)
            const outputVariable =
                filtered.length === 0
                    ? null
                    : filtered.length === 1
                      ? { ...filtered[0], result_path: filtered[0].result_path || null }
                      : filtered.map((m) => ({ ...m, result_path: m.result_path || null }))
            setWorkflowAction(selectedNode.data.id, {
                ...selectedNode.data,
                output_variable: outputVariable,
            } as HogFlowAction)
        },
        [selectedNode, setWorkflowAction]
    )

    const setMappings = useCallback(
        (newMappings: OutputMapping[]) => {
            setMappingsState(newMappings)
            persistMappings(newMappings)
        },
        [persistMappings]
    )

    const [testLoading, setTestLoading] = useState(false)
    const [testError, setTestError] = useState<string | null>(null)
    const [testResultData, setTestResultData] = useState<any>(null)

    // Reset test state when switching nodes
    useEffect(() => {
        setTestError(null)
        setTestResultData(null)
    }, [selectedNode?.data.id])

    const runOutputTest = useCallback(async () => {
        if (!selectedNode || workflow.id === 'new') {
            return
        }

        setTestLoading(true)
        setTestError(null)
        setTestResultData(null)

        try {
            const testLogic = hogFlowEditorTestLogic.findMounted({ id: workflow.id })
            const sampleGlobals = testLogic?.values.sampleGlobals ?? createExampleEvent(workflow.team_id, workflow.name)

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
                    ...testLogic?.values.accumulatedVariables,
                },
            }

            const config = sanitizeWorkflow(JSON.parse(JSON.stringify(workflow)), hogFunctionTemplatesById)

            const result: HogflowTestResult = await api.hogFlows.createTestInvocation(workflow.id, {
                configuration: config,
                globals,
                mock_async_functions: false,
                current_action_id: selectedNode.data.id,
            })

            if (result.status === 'error') {
                setTestError(result.errors?.join(', ') || 'Test execution failed')
            } else if (result.execResult != null) {
                setTestResultData(result.execResult)
            } else {
                setTestError(
                    'Test succeeded but no response data was returned. Make sure the Node.js server has been restarted.'
                )
            }
        } catch (e: any) {
            if (e.data) {
                setTestError(JSON.stringify(e.data, null, 2))
            } else {
                setTestError(e.detail || e.message || 'Failed to run test')
            }
        } finally {
            setTestLoading(false)
        }
    }, [selectedNode, workflow, hogFunctionTemplatesById]) // oxlint-disable-line react-hooks/exhaustive-deps

    const Step = useHogFlowStep(selectedNode?.data)

    if (!selectedNode) {
        return null
    }

    const action = selectedNode.data

    const actionFilters = action.filters ?? {}
    const numberOfActionFilters =
        (actionFilters.events?.length ?? 0) +
        (actionFilters.properties?.length ?? 0) +
        (actionFilters.actions?.length ?? 0)

    return (
        <div className="flex flex-col h-full overflow-hidden">
            <ScrollableShadows
                direction="vertical"
                className="flex-1 min-h-0"
                innerClassName="flex flex-col gap-2 p-3"
                styledScrollbars
            >
                {Step?.renderConfiguration(selectedNode)}
            </ScrollableShadows>

            {isOptOutEligibleAction(action) && (
                <>
                    <LemonDivider className="my-0" />
                    <div className="flex flex-col px-2 py-1">
                        <LemonLabel htmlFor="Message category" className="flex gap-2 justify-between items-center">
                            <span>Message category</span>
                            <div className="flex gap-2">
                                {!categoriesLoading && !categories.length && (
                                    <LemonButton
                                        to={urls.workflows('opt-outs')}
                                        targetBlank
                                        type="secondary"
                                        icon={<IconExternal />}
                                    >
                                        Configure
                                    </LemonButton>
                                )}
                                <CategorySelect
                                    onChange={(categoryId) => {
                                        setWorkflowAction(action.id, {
                                            ...action,
                                            config: {
                                                ...action.config,
                                                message_category_id: categoryId,
                                                message_category_type: categoryId
                                                    ? categories.find((cat) => cat.id === categoryId)?.category_type
                                                    : undefined,
                                            },
                                        } as Extract<HogFlowAction, { type: 'function_email' | 'function_sms' }>)
                                    }}
                                    value={action.config.message_category_id}
                                />
                            </div>
                        </LemonLabel>
                    </div>
                </>
            )}

            {!['trigger', 'exit'].includes(action.type) && (
                <>
                    <LemonDivider className="my-0" />

                    <div className="flex-0">
                        <LemonCollapse
                            embedded
                            panels={[
                                {
                                    key: 'outputs',
                                    header: (
                                        <>
                                            <span className="flex-1">Output variables</span>
                                            <LemonBadge.Number
                                                count={mappings.filter((m) => m.key).length}
                                                showZero={false}
                                            />
                                        </>
                                    ),
                                    content: (
                                        <div className="flex flex-col items-start gap-2 max-h-96 overflow-y-auto">
                                            {mappings.map((mapping, index) => (
                                                <div
                                                    key={index}
                                                    className="flex flex-col gap-1 w-full rounded border border-border p-2"
                                                >
                                                    <div className="flex items-center gap-1">
                                                        <LemonField.Pure label="Variable" className="flex-1">
                                                            <LemonSelect
                                                                options={[
                                                                    { value: '', label: 'Select variable...' },
                                                                    ...(workflow.variables || []).map(({ key }) => ({
                                                                        value: key,
                                                                        label: key,
                                                                    })),
                                                                ]}
                                                                value={mapping.key || ''}
                                                                onChange={(value) => {
                                                                    const updated = [...mappings]
                                                                    updated[index] = {
                                                                        ...updated[index],
                                                                        key: value || '',
                                                                    }
                                                                    setMappings(updated)
                                                                }}
                                                                size="small"
                                                            />
                                                        </LemonField.Pure>
                                                        <LemonButton
                                                            icon={<IconX />}
                                                            size="small"
                                                            tooltip="Remove mapping"
                                                            onClick={() => {
                                                                const updated = mappings.filter((_, i) => i !== index)
                                                                setMappings(updated)
                                                            }}
                                                        />
                                                    </div>
                                                    <LemonField.Pure
                                                        label="Result path"
                                                        info="Specify a path within the step result to store, e.g. 'body.results[0].id'. Leave blank for the entire result."
                                                        className="w-full"
                                                    >
                                                        <LemonInput
                                                            disabledReason={
                                                                !mapping.key ? 'Select a variable first.' : undefined
                                                            }
                                                            type="text"
                                                            prefix={<span>result.</span>}
                                                            value={mapping.result_path}
                                                            onChange={(value) => {
                                                                const updated = [...mappings]
                                                                updated[index] = {
                                                                    ...updated[index],
                                                                    result_path: value,
                                                                }
                                                                setMappingsState(updated)
                                                                persistMappings(updated)
                                                            }}
                                                            placeholder="body.results[0].id"
                                                            size="small"
                                                        />
                                                    </LemonField.Pure>
                                                </div>
                                            ))}
                                            <LemonButton
                                                icon={<IconPlus />}
                                                size="small"
                                                type="secondary"
                                                onClick={() => {
                                                    const updated = [...mappings, { key: '', result_path: '' }]
                                                    setMappings(updated)
                                                }}
                                            >
                                                Add mapping
                                            </LemonButton>
                                            <LemonDivider className="my-1" />
                                            <LemonButton
                                                icon={<IconPlay />}
                                                size="small"
                                                type="primary"
                                                loading={testLoading}
                                                tooltip="Executes a real HTTP request to this step's endpoint and shows the response so you can pick which property to store."
                                                disabledReason={
                                                    workflow.id === 'new'
                                                        ? 'Save the workflow first to test steps'
                                                        : undefined
                                                }
                                                onClick={runOutputTest}
                                            >
                                                Pick from response
                                            </LemonButton>
                                            {testError && (
                                                <LemonBanner type="error" className="w-full">
                                                    {testError}
                                                </LemonBanner>
                                            )}
                                            {testResultData !== null && (
                                                <div className="w-full">
                                                    <p className="text-xs text-secondary mb-1">
                                                        Click a key to use as result path
                                                    </p>
                                                    <div className="max-h-64 overflow-auto border rounded p-1">
                                                        <OutputTestResultTree
                                                            data={testResultData}
                                                            selectedPath={pendingPath || ''}
                                                            onPathSelect={(path) => {
                                                                if (mappings.length <= 1) {
                                                                    if (mappings.length === 0) {
                                                                        setMappings([{ key: '', result_path: path }])
                                                                    } else {
                                                                        const updated = [...mappings]
                                                                        updated[0] = {
                                                                            ...updated[0],
                                                                            result_path: path,
                                                                        }
                                                                        setMappings(updated)
                                                                    }
                                                                    setPendingPath(null)
                                                                } else {
                                                                    setPendingPath(path)
                                                                }
                                                            }}
                                                        />
                                                    </div>
                                                    {pendingPath && mappings.length >= 2 && (
                                                        <div
                                                            ref={(el) => {
                                                                ;(
                                                                    assignToRef as React.MutableRefObject<HTMLDivElement | null>
                                                                ).current = el
                                                                el?.scrollIntoView({
                                                                    behavior: 'smooth',
                                                                    block: 'nearest',
                                                                })
                                                            }}
                                                            className="mt-2 p-2 rounded border border-primary bg-primary-highlight"
                                                        >
                                                            <p className="text-xs font-semibold mb-1">
                                                                Assign{' '}
                                                                <code className="text-xs">result.{pendingPath}</code>{' '}
                                                                to:
                                                            </p>
                                                            <div className="flex flex-wrap gap-1">
                                                                {mappings.map((mapping, index) => (
                                                                    <LemonButton
                                                                        key={index}
                                                                        size="xsmall"
                                                                        type="secondary"
                                                                        onClick={() => {
                                                                            const updated = [...mappings]
                                                                            updated[index] = {
                                                                                ...updated[index],
                                                                                result_path: pendingPath,
                                                                            }
                                                                            setMappings(updated)
                                                                            setPendingPath(null)
                                                                        }}
                                                                    >
                                                                        {mapping.key || `Row ${index + 1}`}
                                                                    </LemonButton>
                                                                ))}
                                                                <LemonButton
                                                                    size="xsmall"
                                                                    type="tertiary"
                                                                    onClick={() => setPendingPath(null)}
                                                                >
                                                                    Cancel
                                                                </LemonButton>
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            )}
                                            <LemonDivider className="my-1" />
                                            <LemonButton
                                                icon={<IconPlus />}
                                                sideIcon={<IconExternal />}
                                                size="small"
                                                type="secondary"
                                                onClick={() => setMode('variables')}
                                            >
                                                New variable
                                            </LemonButton>
                                        </div>
                                    ),
                                },
                                {
                                    key: 'filters',
                                    header: (
                                        <>
                                            <span className="flex-1">Conditions</span>
                                            <LemonBadge.Number count={numberOfActionFilters} showZero={false} />
                                        </>
                                    ),
                                    content: (
                                        <div>
                                            <p>
                                                Add conditions to the step. If these conditions aren't met, the user
                                                will skip this step and continue to the next one.
                                            </p>
                                            <HogFlowPropertyFilters
                                                filtersKey={`action-skip-conditions-${action.id}`}
                                                filters={action.filters ?? {}}
                                                setFilters={(filters) =>
                                                    setWorkflowAction(action.id, { ...action, filters })
                                                }
                                                buttonCopy="Add filter conditions"
                                            />
                                        </div>
                                    ),
                                },
                                {
                                    key: 'on_error',
                                    header: <span className="flex-1">Error handling</span>,
                                    content: (
                                        <div>
                                            <p>
                                                What to do if this step fails (e.g. message could not be sent). By
                                                default, the user will continue to the next step.
                                            </p>
                                            <LemonSelect
                                                options={[
                                                    { value: 'continue', label: 'Continue to next step' },
                                                    { value: 'abort', label: 'Exit the workflow' },
                                                ]}
                                                value={action.on_error || 'abort'}
                                                onChange={(value) =>
                                                    setWorkflowAction(action.id, {
                                                        ...action,
                                                        on_error: value,
                                                    })
                                                }
                                            />
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    </div>
                </>
            )}
        </div>
    )
}
