import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconBalance, IconPlus, IconX } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from '../types'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import {
    cohortPercentagesAddUp,
    normalizeCohortPercentages,
    parseCohortPercentage,
    useDebouncedNameInputs,
} from './utils'

// Print enough precision that the two figures in the imbalance warning cannot contradict each other:
// rounding a 99.996% total to hundredths would claim it adds up to 100% with 0% left over. Number()
// then drops the zeros toFixed pads with, and clears float noise like 0.0040000000000048.
const formatPercentage = (value: number): string => Number(value.toFixed(10)).toString()

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

    // While a percentage field is focused it displays the raw text being typed, keyed by cohort index.
    // Feeding the parsed number straight back as the input's value would drop a trailing decimal
    // point, so a fractional share could never be typed: "3." parses to 3 and the field re-renders
    // without the dot, leaving "3.3" unreachable.
    const [percentageDrafts, setPercentageDrafts] = useState<Record<number, string>>({})

    const updateCohortPercentage = (index: number, value: string): void => {
        setPercentageDrafts((drafts) => ({ ...drafts, [index]: value }))
        const percentage = parseCohortPercentage(value)
        setCohorts(cohorts.map((cohort, i) => (i === index ? { ...cohort, percentage } : cohort)))
    }

    const clearPercentageDraft = (index: number): void => {
        setPercentageDrafts((drafts) => {
            const remaining = { ...drafts }
            delete remaining[index]
            return remaining
        })
    }

    const normalizePercentages = (): void => {
        if (cohorts.length === 0) {
            return
        }
        const normalized = normalizeCohortPercentages(cohorts.length)
        setCohorts(cohorts.map((cohort, i) => ({ ...cohort, percentage: normalized[i] })))
        // Every share is replaced, so any draft still open is stale text sitting over a new value. The
        // button cannot be relied on to blur the field first: Safari leaves focus where it was.
        setPercentageDrafts({})
    }

    const percentages = cohorts.map((cohort) => cohort.percentage)
    const totalPercentage = percentages.reduce((sum, percentage) => sum + percentage, 0)
    const isBalanced = cohortPercentagesAddUp(percentages)
    const shortfall = 100 - totalPercentage

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
                            value={percentageDrafts[index] ?? String(cohort.percentage)}
                            onChange={(e) => updateCohortPercentage(index, e.target.value)}
                            onBlur={() => clearPercentageDraft(index)}
                            className="w-20 px-2 py-1 border rounded"
                        />
                        <span>%</span>
                    </div>
                </div>
            ))}

            {cohorts.length > 0 && !isBalanced && (
                <div className="text-sm text-orange-600">
                    {shortfall > 0
                        ? `These add up to ${formatPercentage(totalPercentage)}%. The remaining ${formatPercentage(shortfall)}% will go to the last cohort.`
                        : `These add up to ${formatPercentage(totalPercentage)}%. Later cohorts will get less than their share, and some may never be used.`}
                </div>
            )}

            <div className="flex gap-2">
                <LemonButton type="secondary" icon={<IconPlus />} onClick={() => addCohort()} className="flex-1">
                    Add cohort
                </LemonButton>
                <LemonButton type="secondary" onClick={normalizePercentages} tooltip="Split evenly across all cohorts">
                    <IconBalance />
                </LemonButton>
            </div>
        </>
    )
}
