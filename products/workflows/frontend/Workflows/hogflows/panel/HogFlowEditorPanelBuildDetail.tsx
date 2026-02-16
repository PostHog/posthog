import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

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

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { urls } from 'scenes/urls'

import { CategorySelect } from 'products/workflows/frontend/OptOuts/CategorySelect'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { isOptOutEligibleAction } from '../steps/types'
import type { HogFlowAction } from '../types'
import { OutputTestResultTree } from './OutputTestResultTree'
import { hogFlowOutputMappingLogic } from './hogFlowOutputMappingLogic'

export function HogFlowEditorPanelBuildDetail(): JSX.Element | null {
    const { selectedNode, workflow, categories, categoriesLoading } = useValues(hogFlowEditorLogic)
    const { setWorkflowAction, setMode } = useActions(hogFlowEditorLogic)
    const { logicProps } = useValues(workflowLogic)
    const { mappings, pendingPath, testLoading, testError, testResultData, shakePickButton } = useValues(
        hogFlowOutputMappingLogic(logicProps)
    )
    const {
        setSelectedActionId,
        setMappings,
        updateMappingResultPath,
        addMapping,
        removeMapping,
        selectPath,
        assignPendingPathToMapping,
        cancelPendingPath,
        runOutputTest,
    } = useActions(hogFlowOutputMappingLogic(logicProps))

    useEffect(() => {
        setSelectedActionId(selectedNode?.data.id ?? null)
    }, [selectedNode?.data.id]) // oxlint-disable-line react-hooks/exhaustive-deps

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
                                                                    ...(workflow.variables || [])
                                                                        .filter(
                                                                            ({ key }) =>
                                                                                key === mapping.key ||
                                                                                !mappings.some((m) => m.key === key)
                                                                        )
                                                                        .map(({ key }) => ({
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
                                                            onClick={() => removeMapping(index)}
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
                                                            onChange={(value) => updateMappingResultPath(index, value)}
                                                            placeholder="body.results[0].id"
                                                            size="small"
                                                        />
                                                    </LemonField.Pure>
                                                </div>
                                            ))}
                                            <div className="flex gap-2 w-full">
                                                <LemonButton
                                                    icon={<IconPlus />}
                                                    size="small"
                                                    type="secondary"
                                                    onClick={() => addMapping()}
                                                >
                                                    Add mapping
                                                </LemonButton>
                                                <LemonButton
                                                    icon={<IconPlay />}
                                                    size="small"
                                                    type="primary"
                                                    className={shakePickButton ? 'animate-shake' : ''}
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
                                            </div>
                                            {testError && (
                                                <LemonBanner type="error" className="w-full">
                                                    {testError}
                                                </LemonBanner>
                                            )}
                                            {testResultData !== null && (
                                                <div
                                                    className="w-full"
                                                    ref={(el) =>
                                                        el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
                                                    }
                                                >
                                                    <p className="text-xs text-secondary mb-1">
                                                        Click a key to use as result path
                                                    </p>
                                                    <div className="max-h-64 overflow-auto border rounded p-1">
                                                        <OutputTestResultTree
                                                            data={testResultData}
                                                            selectedPath={pendingPath || ''}
                                                            onPathSelect={(path) => selectPath(path)}
                                                        />
                                                    </div>
                                                    {pendingPath && mappings.length >= 2 && (
                                                        <div
                                                            ref={(el) =>
                                                                el?.scrollIntoView({
                                                                    behavior: 'smooth',
                                                                    block: 'nearest',
                                                                })
                                                            }
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
                                                                        onClick={() =>
                                                                            assignPendingPathToMapping(
                                                                                index,
                                                                                pendingPath!
                                                                            )
                                                                        }
                                                                    >
                                                                        {mapping.key || `Row ${index + 1}`}
                                                                    </LemonButton>
                                                                ))}
                                                                <LemonButton
                                                                    size="xsmall"
                                                                    type="tertiary"
                                                                    onClick={() => cancelPendingPath()}
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
