import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconPlus, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { EXIT_NODE_ID } from '../../workflowLogic'
import { HogFlowPropertyFilters } from '../filters/HogFlowFilters'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from '../types'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { getBranchRemovalDisabledReason, removeBranchEdge, useDebouncedNameInputs } from './utils'

export function StepConditionalBranchConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'conditional_branch' }>>
}): JSX.Element {
    const action = node.data
    const { conditions } = action.config

    const { edgesByActionId, workflow } = useValues(hogFlowEditorLogic)
    const { setWorkflowAction, setWorkflowActionEdges, setWorkflowInfo } = useActions(hogFlowEditorLogic)

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
    const isExitOnNoMatch = continueEdge?.to === EXIT_NODE_ID

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

    const exitOnNoMatch = (): void => {
        if (!continueEdge) {
            return
        }

        // Find the target of the continue edge (where "no match" leads)
        const noMatchTargetId = continueEdge.to

        // Collect all node IDs reachable from noMatchTargetId (excluding EXIT)
        const toDelete = new Set<string>()
        const queue = [noMatchTargetId]
        while (queue.length > 0) {
            const id = queue.shift()!
            if (!id || id === EXIT_NODE_ID || toDelete.has(id)) {
                continue
            }
            toDelete.add(id)
            workflow.edges.forEach((edge: HogFlow['edges'][number]) => {
                if (edge.from === id) {
                    queue.push(edge.to)
                }
            })
        }

        // Update edges: redirect continue edge to EXIT and remove all edges to deleted nodes
        const updatedEdges = workflow.edges
            .map((edge: HogFlow['edges'][number]) =>
                edge.from === action.id && edge.type === 'continue' ? { ...edge, to: EXIT_NODE_ID } : edge
            )
            .filter((edge: HogFlow['edges'][number]) => !toDelete.has(edge.to) && !toDelete.has(edge.from))
        const updatedActions = workflow.actions.filter((a: HogFlowAction) => !toDelete.has(a.id))
        setWorkflowInfo({ actions: updatedActions, edges: updatedEdges })
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
            <div className="flex flex-col gap-2 p-2 rounded border mt-2">
                <LemonLabel>No match</LemonLabel>
                <LemonCheckbox
                    checked={isExitOnNoMatch}
                    onChange={(checked) => {
                        if (!checked || !continueEdge) {
                            return
                        }
                        LemonDialog.open({
                            title: 'Exit workflow on no match?',
                            description:
                                'This will remove all steps on the "No match" path and redirect it straight to the exit node.',
                            primaryButton: {
                                children: 'Remove and exit',
                                status: 'danger',
                                onClick: exitOnNoMatch,
                            },
                            secondaryButton: {
                                children: 'Cancel',
                            },
                        })
                    }}
                    disabledReason={
                        isExitOnNoMatch ? 'To reconnect, drag a step onto the "No match" edge in the canvas' : undefined
                    }
                    label="Exit workflow immediately"
                />
            </div>
        </>
    )
}
