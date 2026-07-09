import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconBalance, IconPlus, IconX } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from '../types'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { useDebouncedNameInputs } from './utils'

const MAX_VARIANTS = 4

export function StepExperimentBranchConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'experiment_branch' }>>
}): JSX.Element {
    const action = node.data
    const { variants, winner } = action.config

    const { edgesByActionId } = useValues(hogFlowEditorLogic)
    const { setWorkflowAction, setWorkflowActionEdges } = useActions(hogFlowEditorLogic)

    const nodeEdges = edgesByActionId[action.id] ?? []

    const setVariants = (
        variants: Extract<HogFlowAction, { type: 'experiment_branch' }>['config']['variants']
    ): void => {
        setWorkflowAction(action.id, {
            ...action,
            config: { ...action.config, variants },
        })
    }

    const { localNames: localVariantNames, handleNameChange } = useDebouncedNameInputs(variants, setVariants)

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

    const addVariant = (): void => {
        const continueEdge = nodeEdges.find((edge) => edge.type === 'continue' && edge.from === action.id)
        if (!continueEdge) {
            throw new Error('Continue edge not found')
        }

        // Variant keys are stable identifiers (they feed the assignment hash), so pick the first free one
        const usedKeys = new Set(variants.map((variant) => variant.key))
        let suffix = variants.length
        while (usedKeys.has(`test-${suffix}`)) {
            suffix++
        }

        setVariants([...variants, { key: `test-${suffix}`, percentage: 25 }])
        setWorkflowActionEdges(action.id, [
            ...branchEdges,
            {
                from: action.id,
                to: continueEdge.to,
                type: 'branch',
                index: variants.length,
            },
            ...nonBranchEdges,
        ])
    }

    const removeVariant = (index: number): void => {
        const newBranchEdges = branchEdges.filter((_, i) => i !== index).map((edge, i) => ({ ...edge, index: i }))
        setVariants(variants.filter((_, i) => i !== index))
        setWorkflowActionEdges(action.id, [...newBranchEdges, ...nonBranchEdges])
    }

    const updateVariantPercentage = (index: number, percentage: number): void => {
        setVariants(variants.map((variant, i) => (i === index ? { ...variant, percentage } : variant)))
    }

    const normalizePercentages = (): void => {
        const count = variants.length
        if (count === 0) {
            return
        }
        const base = Math.floor(100 / count)
        const remainder = 100 - base * count
        const normalized = variants.map((variant, i) => {
            // Distribute remainder to the first variants
            return { ...variant, percentage: base + (i < remainder ? 1 : 0) }
        })
        setVariants(normalized)
    }

    const totalPercentage = variants.reduce((sum, variant) => sum + variant.percentage, 0)

    return (
        <>
            <StepSchemaErrors />

            {winner && (
                <LemonBanner type="info">
                    Winner promoted: all new entrants take the <strong>{winner}</strong> branch.
                </LemonBanner>
            )}

            <p className="mb-0 text-sm text-secondary">
                People entering this step are split between variants deterministically, so a person always gets the same
                variant.
            </p>

            {variants.map((variant, index) => (
                <div key={index} className="flex flex-col gap-2 p-2 rounded border">
                    <div className="flex justify-between items-center">
                        <LemonLabel>{index === 0 ? 'Control' : `Variant ${variant.key}`}</LemonLabel>
                        {index > 0 && (
                            <LemonButton size="xsmall" icon={<IconX />} onClick={() => removeVariant(index)} />
                        )}
                    </div>

                    <LemonInput
                        value={localVariantNames[index] || ''}
                        onChange={(value) => handleNameChange(index, value)}
                        placeholder={index === 0 ? 'Control' : `Variant ${index}`}
                        size="small"
                    />

                    <div className="flex items-center gap-2">
                        <input
                            type="number"
                            min="0"
                            max="100"
                            value={variant.percentage}
                            onChange={(e) => updateVariantPercentage(index, parseInt(e.target.value) || 0)}
                            className="w-20 px-2 py-1 border rounded"
                        />
                        <span>%</span>
                    </div>
                </div>
            ))}

            {totalPercentage !== 100 && (
                <div className="text-sm text-orange-600">Total percentage: {totalPercentage}% (should equal 100%)</div>
            )}

            <div className="flex gap-2">
                <LemonButton
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={() => addVariant()}
                    className="flex-1"
                    disabledReason={
                        variants.length >= MAX_VARIANTS
                            ? `A maximum of ${MAX_VARIANTS} variants is supported`
                            : undefined
                    }
                >
                    Add variant
                </LemonButton>
                <LemonButton type="secondary" onClick={normalizePercentages} tooltip="Normalize variant percentages">
                    <IconBalance />
                </LemonButton>
            </div>
        </>
    )
}
