import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from '../types'
import { StepSchemaErrors } from './components/StepSchemaErrors'

export function StepConditionalBranchConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'conditional_branch' }>>
}): JSX.Element {
    const action = node.data
    const { conditions } = action.config

    const { edgesByActionId, selectedNodeCanBeDeleted } = useValues(hogFlowEditorLogic)
    const { setCampaignAction, setCampaignActionEdges } = useActions(hogFlowEditorLogic)

    const nodeEdges = edgesByActionId[action.id]

    const [branchEdges, nonBranchEdges] = useMemo(() => {
        const branchEdges: HogFlow['edges'] = []
        const nonBranchEdges: HogFlow['edges'] = []

        nodeEdges.forEach((edge) => {
            if (edge.type === 'branch' && edge.from === action.id) {
                branchEdges.push(edge)
            } else {
                nonBranchEdges.push(edge)
            }
        })

        return [branchEdges.sort((a, b) => (a.index ?? 0) - (b.index ?? 0)), nonBranchEdges]
    }, [nodeEdges, action.id])

    const setConditions = (
        conditions: Extract<HogFlowAction, { type: 'conditional_branch' }>['config']['conditions']
    ): void => {
        // TODO: Find all related edges. We can only delete those that are the same as the continue edge.
        // All others should be disabled for deletion until the subbranch is removed

        // For condition modifiers we need to setup the branches as well
        setCampaignAction(action.id, {
            ...action,
            config: { ...action.config, conditions },
        })
    }

    const addCondition = (): void => {
        const continueEdge = nodeEdges.find((edge) => edge.type === 'continue' && edge.from === action.id)
        if (!continueEdge) {
            throw new Error('Continue edge not found')
        }

        setConditions([
            ...conditions,
            { filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events' }] } },
        ])
        setCampaignActionEdges(action.id, [
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
        // Branch edges are pre-sorted
        // We just need to remove the edge and re-assign the indexes
        const newBranchEdges = branchEdges.filter((_, i) => i !== index).map((edge, i) => ({ ...edge, index: i }))
        setConditions(conditions.filter((_, i) => i !== index))
        // Branch edges come first as they are sorted to show on the left
        setCampaignActionEdges(action.id, [...newBranchEdges, ...nonBranchEdges])
    }

    return (
        <>
            <StepSchemaErrors />
            {conditions.map((condition, index) => (
                <div key={index} className="flex flex-col gap-2 p-2 rounded border">
                    <div className="flex justify-between items-center">
                        <LemonLabel>Condition {index + 1}</LemonLabel>
                        <LemonButton
                            size="xsmall"
                            icon={<IconX />}
                            onClick={() => removeCondition(index)}
                            disabledReason={selectedNodeCanBeDeleted ? undefined : 'Clean up branching steps first'}
                        />
                    </div>

                    <HogFlowPropertyFilters
                        actionId={`${action.id}.${index}`}
                        filters={condition.filters ?? {}}
                        setFilters={(filters) =>
                            setConditions(
                                conditions.map((condition, i) => (i === index ? { filters: filters ?? {} } : condition))
                            )
                        }
                        typeKey={`campaign-trigger-${index}`}
                    />
                </div>
            ))}

            <LemonButton type="secondary" icon={<IconPlus />} onClick={() => addCondition()}>
                Add condition
            </LemonButton>
        </>
    )
}
