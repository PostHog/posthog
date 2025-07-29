import { IconPercentage, IconPlus, IconX } from '@posthog/icons'
import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { useMemo } from 'react'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'

export const StepRandomCohortBranch: HogFlowStep<'random_cohort_branch'> = {
    type: 'random_cohort_branch',
    name: 'Random cohort branch',
    description: 'Randomly branch off to a different path based on cohort percentages.',
    icon: <IconPercentage />,
    renderNode: (props) => <StepRandomCohortBranchNode {...props} />,
    renderConfiguration: (node) => <StepRandomCohortBranchConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Random cohort',
                description: '',
                type: 'random_cohort_branch',
                on_error: 'continue',
                config: {
                    cohorts: [
                        {
                            percentage: 50,
                        },
                    ],
                },
            },
            branchEdges: 1,
        }
    },
}

function StepRandomCohortBranchNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepRandomCohortBranchConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'random_cohort_branch' }>>
}): JSX.Element {
    const action = node.data
    const { cohorts } = action.config

    const { edgesByActionId } = useValues(hogFlowEditorLogic)
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

    const setCohorts = (
        cohorts: Extract<HogFlowAction, { type: 'random_cohort_branch' }>['config']['cohorts']
    ): void => {
        setCampaignAction(action.id, {
            ...action,
            config: { ...action.config, cohorts },
        })
    }

    const addCohort = (): void => {
        const continueEdge = nodeEdges.find((edge) => edge.type === 'continue' && edge.from === action.id)
        if (!continueEdge) {
            throw new Error('Continue edge not found')
        }

        setCohorts([...cohorts, { percentage: 25 }])
        setCampaignActionEdges(action.id, [
            ...branchEdges,
            {
                from: action.id,
                to: continueEdge.to,
                type: 'branch',
                index: cohorts.length,
            },
            ...nonBranchEdges,
        ])
    }

    const removeCohort = (index: number): void => {
        const newBranchEdges = branchEdges.filter((_, i) => i !== index).map((edge, i) => ({ ...edge, index: i }))
        setCohorts(cohorts.filter((_, i) => i !== index))
        setCampaignActionEdges(action.id, [...newBranchEdges, ...nonBranchEdges])
    }

    const updateCohortPercentage = (index: number, percentage: number): void => {
        setCohorts(cohorts.map((cohort, i) => (i === index ? { percentage } : cohort)))
    }

    const totalPercentage = cohorts.reduce((sum, cohort) => sum + cohort.percentage, 0)

    return (
        <>
            {cohorts.map((cohort, index) => (
                <div key={index} className="flex flex-col gap-2 p-2 rounded border">
                    <div className="flex justify-between items-center">
                        <LemonLabel>Cohort {index + 1}</LemonLabel>
                        <LemonButton size="xsmall" icon={<IconX />} onClick={() => removeCohort(index)} />
                    </div>

                    <div className="flex items-center gap-2">
                        <input
                            type="number"
                            min="0"
                            max="100"
                            value={cohort.percentage}
                            onChange={(e) => updateCohortPercentage(index, parseInt(e.target.value) || 0)}
                            className="w-20 px-2 py-1 border rounded"
                        />
                        <span>%</span>
                    </div>
                </div>
            ))}

            {totalPercentage !== 100 && (
                <div className="text-sm text-orange-600">Total percentage: {totalPercentage}% (should equal 100%)</div>
            )}

            <LemonButton type="secondary" icon={<IconPlus />} onClick={() => addCohort()}>
                Add cohort
            </LemonButton>
        </>
    )
}
