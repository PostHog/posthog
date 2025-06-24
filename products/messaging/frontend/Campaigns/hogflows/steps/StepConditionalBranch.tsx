import { IconDecisionTree, IconPlus, IconX } from '@posthog/icons'
import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepConditionalBranch: HogFlowStep<'conditional_branch'> = {
    type: 'conditional_branch',
    renderNode: (props) => <StepConditionalBranchNode {...props} />,
    renderConfiguration: (node) => <StepConditionalBranchConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Conditional',
                description: '',
                type: 'conditional_branch',
                on_error: 'continue',
                config: {
                    conditions: [
                        {
                            filters: {
                                events: [
                                    {
                                        id: '$pageview',
                                        name: '$pageview',
                                        type: 'events',
                                    },
                                ],
                            },
                        },
                    ],
                },
            },
            branchEdges: 1,
        }
    },
}

function StepConditionalBranchNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView name={data.name} icon={<IconDecisionTree className="text-green-400" />} selected={false} />
}

function StepConditionalBranchConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'conditional_branch' }>>
}): JSX.Element {
    const action = node.data
    const { conditions } = action.config

    const { edgesByActionId } = useValues(hogFlowEditorLogic)
    const { setCampaignAction, setCampaignEdges } = useActions(hogFlowEditorLogic)

    const edges = edgesByActionId[action.id]

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
        const continueEdge = edges.find((edge) => edge.type === 'continue' && edge.from === action.id)
        if (!continueEdge) {
            throw new Error('Continue edge not found')
        }

        setConditions([
            ...conditions,
            { filters: { events: [{ id: '$pageview', name: '$pageview', type: 'events' }] } },
        ])
        setCampaignEdges([
            ...edges,
            {
                from: action.id,
                to: continueEdge.to,
                type: 'branch',
                index: conditions.length,
            },
        ])
    }

    return (
        <>
            <div className="flex flex-col">
                <p className="mb-1 text-lg font-semibold">Conditional branch</p>
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>

            {conditions.map((condition, index) => (
                <div key={index} className="flex flex-col gap-2 p-2 rounded border">
                    <div className="flex justify-between items-center">
                        <LemonLabel>Condition {index + 1}</LemonLabel>
                        <LemonButton
                            size="small"
                            icon={<IconX />}
                            onClick={() => {
                                setConditions(conditions.filter((_, i) => i !== index))
                            }}
                        />
                    </div>

                    <ActionFilter
                        filters={condition.filters ?? {}}
                        setFilters={(filters) =>
                            setConditions(conditions.map((condition, i) => (i === index ? { filters } : condition)))
                        }
                        typeKey={`campaign-trigger-${index}`}
                        mathAvailability={MathAvailability.None}
                        hideRename
                        hideDuplicate
                        showNestedArrow={false}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                        propertiesTaxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.Elements,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.HogQLExpression,
                        ]}
                        propertyFiltersPopover
                        addFilterDefaultOptions={{
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                        }}
                        buttonProps={{
                            type: 'secondary',
                        }}
                        buttonCopy="Add match filters"
                    />
                </div>
            ))}

            <LemonButton type="secondary" icon={<IconPlus />} onClick={() => addCondition()}>
                Add condition
            </LemonButton>
        </>
    )
}
