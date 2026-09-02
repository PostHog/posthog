import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus, IconX } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from '../types'
import { batchTriggerLogic } from './batchTriggerLogic'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { getBranchRemovalDisabledReason, isCountableCondition, removeBranchEdge, useDebouncedNameInputs } from './utils'

type ConditionFilters = Extract<
    HogFlowAction,
    { type: 'conditional_branch' }
>['config']['conditions'][number]['filters']

function ConditionAudienceEstimate({
    actionId,
    index,
    filters,
}: {
    actionId: string
    index: number
    filters: ConditionFilters
}): JSX.Element | null {
    // Counting persons, not sends, so this deliberately skips the email dedup the batch trigger applies.
    const { blastRadius, blastRadiusLoading, blastRadiusError } = useValues(
        batchTriggerLogic({
            id: `${actionId}-condition-${index}`,
            filters: { properties: filters?.properties ?? [] },
        })
    )

    if (blastRadiusLoading) {
        return <Spinner className="text-xs" />
    }

    // A failed estimate is not worth interrupting the person over: the condition itself is still valid.
    if (blastRadiusError || !blastRadius) {
        return null
    }

    const { affected, total } = blastRadius
    if (affected == null || total == null || total === 0) {
        return null
    }

    const percentage = (affected / total) * 100
    const roundedPercentage = percentage > 0 && percentage < 1 ? '<1' : humanFriendlyNumber(percentage, 1)

    return (
        <Tooltip title="Share of all persons matching this condition right now. Each person is checked again when they reach this step.">
            <span className="text-xs text-muted whitespace-nowrap">
                {roundedPercentage}% of persons ({humanFriendlyNumber(affected)} of {humanFriendlyNumber(total)})
            </span>
        </Tooltip>
    )
}

export function StepConditionalBranchConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'conditional_branch' }>>
}): JSX.Element {
    const action = node.data
    const conditions = action.config.conditions ?? []

    const { edgesByActionId } = useValues(hogFlowEditorLogic)
    const { setWorkflowAction, setWorkflowActionEdges } = useActions(hogFlowEditorLogic)

    const nodeEdges = edgesByActionId[action.id] ?? []

    const setConditions = (
        conditions: Extract<HogFlowAction, { type: 'conditional_branch' }>['config']['conditions']
    ): void => {
        // For condition modifiers we need to setup the branches as well
        setWorkflowAction(action.id, {
            ...action,
            config: { ...action.config, conditions },
        })
    }

    const { localNames: localConditionNames, handleNameChange } = useDebouncedNameInputs(conditions, setConditions)

    const [branchEdges, nonBranchEdges] = useMemo(() => {
        const branchEdges: HogFlow['edges'] = []
        const nonBranchEdges: HogFlow['edges'] = []

        nodeEdges?.forEach((edge) => {
            if (edge.type === 'branch' && edge.from === action.id) {
                branchEdges.push(edge)
            } else {
                nonBranchEdges.push(edge)
            }
        })

        return [branchEdges.sort((a, b) => (a.index ?? 0) - (b.index ?? 0)), nonBranchEdges]
    }, [nodeEdges, action.id])

    const continueEdge = nodeEdges.find((edge) => edge.type === 'continue' && edge.from === action.id)

    const addCondition = (): void => {
        if (!continueEdge) {
            throw new Error('Continue edge not found')
        }

        setConditions([...conditions, { filters: {} }])
        setWorkflowActionEdges(action.id, [
            ...branchEdges,
            {
                from: action.id,
                to: continueEdge.to,
                type: 'branch',
                index: conditions.length,
            },
            ...nonBranchEdges,
        ])
    }

    const removeCondition = (index: number): void => {
        setConditions(conditions.filter((_, i) => i !== index))
        // Branch edges come first as they are sorted to show on the left
        setWorkflowActionEdges(action.id, [...removeBranchEdge(branchEdges, index), ...nonBranchEdges])
    }

    return (
        <>
            <StepSchemaErrors />
            {conditions.map((condition, index) => (
                <div key={index} className="flex flex-col gap-2 p-2 rounded border">
                    <div className="flex justify-between items-center gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                            <LemonLabel>Condition {index + 1}</LemonLabel>
                            {isCountableCondition(condition.filters) && (
                                <ConditionAudienceEstimate
                                    actionId={action.id}
                                    index={index}
                                    filters={condition.filters}
                                />
                            )}
                        </div>
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={() => removeCondition(index)}
                            disabledReason={getBranchRemovalDisabledReason(branchEdges, index, edgesByActionId)}
                        />
                    </div>

                    <HogFlowPropertyFilters
                        filtersKey={`condition-branch-condition-${action.id}-${index}`}
                        filters={condition.filters ?? {}}
                        setFilters={(filters) =>
                            setConditions(
                                conditions.map((condition, i) =>
                                    i === index ? { ...condition, filters: filters ?? {} } : condition
                                )
                            )
                        }
                        typeKey={`workflow-trigger-${index}`}
                    />

                    <LemonField.Pure label="Condition name (optional)">
                        <LemonInput
                            value={localConditionNames[index] || ''}
                            onChange={(value) => handleNameChange(index, value)}
                            placeholder={`If condition #${index + 1} matches`}
                            size="small"
                        />
                    </LemonField.Pure>
                </div>
            ))}

            <LemonButton type="secondary" icon={<IconPlus />} onClick={() => addCondition()} className="mt-2">
                Add condition
            </LemonButton>
        </>
    )
}
