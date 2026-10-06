import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { objectsEqual } from 'lib/utils/objects'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { TrendsFormulaNode } from '~/queries/schema/schema-general'
import { EditorFilterProps } from '~/types'

// When updating this regex, remember to update the regex with the same name in mixins/common.py
const ALLOWED_FORMULA_CHARACTERS = /^[a-zA-Z \-*^0-9+/().]+$/

export function TrendsFormula({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { formulaNodes, hasFormula } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter, removeFormulaNode } = useActions(insightVizDataLogic(insightProps))

    const [localValues, setLocalValues] = useState<TrendsFormulaNode[]>(formulaNodes)

    useEffect(() => {
        // Don't clear the formulas so that the values are still there after toggling the formula switch.
        // formulaNodes is [] (truthy) when no formula is set, so check length to fall through to the
        // hasFormula branch that seeds one empty input when formula mode is toggled on.
        if (formulaNodes && formulaNodes.length > 0) {
            // Merge incoming formulas with existing local fields, maintaining order. The source
            // query editor can change the query while this editor stays mounted, so the counts
            // can differ.
            setLocalValues((prev) => {
                const merged: TrendsFormulaNode[] = []
                let backendIndex = 0
                for (const localValue of prev) {
                    if (localValue.formula.trim() === '') {
                        merged.push(localValue)
                    } else if (backendIndex < formulaNodes.length) {
                        merged.push(formulaNodes[backendIndex])
                        backendIndex++
                    }
                }
                while (backendIndex < formulaNodes.length) {
                    merged.push(formulaNodes[backendIndex])
                    backendIndex++
                }
                return merged
            })
        } else if (hasFormula) {
            // The query can lose every formula from outside this editor. Drop the fields that
            // held them, so a later blur cannot write a formula back that the query no longer
            // has, and keep one blank field for the user to type in.
            setLocalValues((prev) => {
                const blanks = prev.filter((node) => node.formula.trim() === '')
                if (blanks.length === 0) {
                    return [{ formula: '' }]
                }
                return blanks.length === prev.length ? prev : blanks
            })
        }
    }, [formulaNodes, hasFormula]) // oxlint-disable-line react-hooks/exhaustive-deps

    const updateFormulas = (newValues: TrendsFormulaNode[]): void => {
        // Filter out empty values when updating the query but keep them in local state
        const filledValues = newValues.filter((v) => v.formula.trim() !== '')
        // Blurring a field the user did not change is the common case, so skip the query update
        // and the refetch it triggers.
        if (objectsEqual(filledValues, formulaNodes)) {
            return
        }

        // Always use formulaNodes for consistency
        updateInsightFilter({
            formula: undefined,
            formulas: undefined,
            formulaNodes: filledValues,
        })
    }

    const handleFormulaChange = (index: number, value: string): void => {
        const newValues = [...localValues]
        let changedValue = value.toLocaleUpperCase()
        // Only allow typing of allowed characters
        changedValue = changedValue
            .split('')
            .filter((d) => ALLOWED_FORMULA_CHARACTERS.test(d))
            .join('')
        newValues[index] = { ...newValues[index], formula: changedValue }
        setLocalValues(newValues)
    }

    const handleCustomNameChange = (index: number, value: string): void => {
        const newValues = [...localValues]
        newValues[index] = { ...newValues[index], custom_name: value }
        setLocalValues(newValues)
    }

    const handleFormulaBlur = (e: React.FocusEvent<HTMLInputElement>): void => {
        // Ignore TrendsFormulaLabel switch click to prevent conflicting updateInsightFilter calls
        if ((e.relatedTarget as HTMLElement | undefined)?.id !== 'trends-formula-switch') {
            updateFormulas(localValues)
        }
    }

    const handleCustomNameBlur = (): void => {
        updateFormulas(localValues)
    }

    const handleFormulaEnter = (): void => {
        updateFormulas(localValues)
    }

    const addFormula = (): void => {
        setLocalValues([...localValues, { formula: '' }])
    }

    const removeFormula = (index: number): void => {
        const newValues = localValues.filter((_, i) => i !== index)
        setLocalValues(newValues)
        removeFormulaNode(newValues)
    }

    return hasFormula ? (
        <div className="deprecated-space-y-2">
            {localValues.map((value, index) => (
                <div key={index} className="space-y-1">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            className="flex-1"
                            placeholder="Example: (A + B) / 100"
                            size="small"
                            autoFocus={index === localValues.length - 1}
                            value={value.formula}
                            onChange={(value) => handleFormulaChange(index, value)}
                            onBlur={handleFormulaBlur}
                            onPressEnter={handleFormulaEnter}
                        />
                        <LemonInput
                            className="flex-1"
                            placeholder="Formula name (optional)"
                            size="small"
                            value={value.custom_name || ''}
                            onChange={(value) => handleCustomNameChange(index, value)}
                            onBlur={handleCustomNameBlur}
                            onPressEnter={handleFormulaEnter}
                        />
                        <LemonButton
                            icon={<IconTrash />}
                            status="alt"
                            onClick={() => removeFormula(index)}
                            title={
                                localValues.length === 1 ? 'Remove formula and disable formula mode' : 'Remove formula'
                            }
                        />
                    </div>
                </div>
            ))}
            <div>
                <LemonButton icon={<IconPlusSmall />} type="tertiary" size="small" onClick={addFormula}>
                    Add formula
                </LemonButton>
            </div>
        </div>
    ) : null
}
