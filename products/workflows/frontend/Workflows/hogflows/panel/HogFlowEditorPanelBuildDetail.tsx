import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { IconExternal, IconPlay, IconPlus } from '@posthog/icons'
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

export function HogFlowEditorPanelBuildDetail(): JSX.Element | null {
    const { selectedNode, workflow, categories, categoriesLoading, hogFunctionTemplatesById } =
        useValues(hogFlowEditorLogic)
    const { setWorkflowAction, setMode } = useActions(hogFlowEditorLogic)

    /**
     * Tricky: Since resultPath is stored inside an object, we need separate state to manage
     * its value to prevent cursor jumping while typing. Updating the parent object causes
     * a re-render due to the new object reference being set on each keystroke.
     */
    const [outputResultPath, setOutputResultPath] = useState(selectedNode?.data.output_variable?.result_path || '')
    useEffect(() => {
        if (selectedNode?.data.output_variable?.key) {
            setWorkflowAction(selectedNode.data.id, {
                ...selectedNode.data,
                output_variable: {
                    ...selectedNode.data.output_variable,
                    result_path: outputResultPath ?? null,
                },
            } as HogFlowAction)
        }
    }, [outputResultPath]) // oxlint-disable-line react-hooks/exhaustive-deps

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
                                    header: <span className="flex-1">Output variable</span>,
                                    content: (
                                        <div className="flex flex-col items-start gap-2">
                                            <LemonField.Pure label="Select a workflow variable to store the output of this step">
                                                <LemonSelect
                                                    options={[
                                                        { value: null, label: 'Do not store' },
                                                        ...(workflow.variables || []).map(({ key }) => ({
                                                            value: key,
                                                            label: key,
                                                        })),
                                                    ]}
                                                    value={action.output_variable?.key || null}
                                                    onChange={(value) =>
                                                        setWorkflowAction(action.id, {
                                                            ...action,
                                                            output_variable: value
                                                                ? { key: value, result_path: null }
                                                                : null,
                                                        })
                                                    }
                                                />
                                            </LemonField.Pure>
                                            <LemonField.Pure
                                                label="Result path (optional)"
                                                info="Specify a path within the step result to store. For example, to store a user ID from a webhook response, you might use 'body.results[0].id'. To store the entire result, leave this blank."
                                                className="w-full"
                                            >
                                                <LemonInput
                                                    disabledReason={
                                                        !action.output_variable?.key
                                                            ? 'Select a variable above to enable setting a result path.'
                                                            : undefined
                                                    }
                                                    type="text"
                                                    prefix={<span>result.</span>}
                                                    value={outputResultPath}
                                                    onChange={(value) => setOutputResultPath(value)}
                                                    placeholder="body.results[0].id"
                                                />
                                            </LemonField.Pure>
                                            <LemonButton
                                                icon={<IconPlay />}
                                                size="small"
                                                type="secondary"
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
                                                            selectedPath={outputResultPath}
                                                            onPathSelect={(path) => {
                                                                setOutputResultPath(path)
                                                            }}
                                                        />
                                                    </div>
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
