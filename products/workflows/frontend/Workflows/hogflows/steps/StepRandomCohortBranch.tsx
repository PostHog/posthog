import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconBalance, IconPlus, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from '../types'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { useDebouncedNameInputs } from './utils'

export function StepRandomCohortBranchConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'random_cohort_branch' }>>
}): JSX.Element {
    const action = node.data
    const cohorts = action.config.cohorts ?? []

    const { edgesByActionId } = useValues(hogFlowEditorLogic)
    const { setWorkflowAction, setWorkflowActionEdges } = useActions(hogFlowEditorLogic)

    const nodeEdges = edgesByActionId[action.id] ?? []

    const setCohorts = (
        cohorts: Extract<HogFlowAction, { type: 'random_cohort_branch' }>['config']['cohorts']
    ): void => {
        setWorkflowAction(action.id, {
            ...action,
            config: { ...action.config, cohorts },
        })
    }

    const { localNames: localCohortNames, handleNameChange } = useDebouncedNameInputs(cohorts, setCohorts)

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

    const addCohort = (): void => {
        const continueEdge = nodeEdges.find((edge) => edge.type === 'continue' && edge.from === action.id)
        if (!continueEdge) {
            throw new Error('Continue edge not found')
        }

        setCohorts([...cohorts, { percentage: 25 }])
        setWorkflowActionEdges(action.id, [
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
        setWorkflowActionEdges(action.id, [...newBranchEdges, ...nonBranchEdges])
    }

    const updateCohortPercentage = (index: number, percentage: number): void => {
        setCohorts(cohorts.map((cohort, i) => (i === index ? { ...cohort, percentage } : cohort)))
    }

    const normalizePercentages = (): void => {
        const count = cohorts.length
        if (count === 0) {
            return
        }
        // Cumulative boundaries in hundredths of a percent, so the shares stay as even as two decimals
        // allow and still add up to exactly 100 (3 cohorts -> 33.33 / 33.34 / 33.33).
        const boundary = (i: number): number => Math.round((i * 10000) / count)
        setCohorts(cohorts.map((cohort, i) => ({ ...cohort, percentage: (boundary(i + 1) - boundary(i)) / 100 })))
    }

    const totalPercentage = Math.round(cohorts.reduce((sum, cohort) => sum + cohort.percentage, 0) * 100) / 100

    return (
        <>
            <StepSchemaErrors />

            {cohorts.map((cohort, index) => (
                <div key={index} className="flex flex-col gap-2 p-2 rounded border">
                    <div className="flex justify-between items-center">
                        <LemonLabel>Cohort {index + 1}</LemonLabel>
                        <LemonButton size="xsmall" icon={<IconX />} onClick={() => removeCohort(index)} />
                    </div>

                    <LemonInput
                        value={localCohortNames[index] || ''}
                        onChange={(value) => handleNameChange(index, value)}
                        placeholder={`Cohort #${index + 1}`}
                        size="small"
                    />

                    <div className="flex items-center gap-2">
                        <input
                            type="number"
                            min="0"
                            max="100"
                            step="any"
                            value={cohort.percentage}
                            onChange={(e) => updateCohortPercentage(index, parseFloat(e.target.value) || 0)}
                            className="w-20 px-2 py-1 border rounded"
                        />
                        <span>%</span>
                    </div>
                </div>
            ))}

            {totalPercentage !== 100 && (
                <div className="text-sm text-orange-600">
                    Cohorts add up to {totalPercentage}%, not 100%. Traffic is still split in these proportions.
                </div>
            )}

            <div className="flex gap-2">
                <LemonButton type="secondary" icon={<IconPlus />} onClick={() => addCohort()} className="flex-1">
                    Add cohort
                </LemonButton>
                <LemonButton type="secondary" onClick={normalizePercentages} tooltip="Normalize cohort percentages">
                    <IconBalance />
                </LemonButton>
            </div>
        </>
    )
}
