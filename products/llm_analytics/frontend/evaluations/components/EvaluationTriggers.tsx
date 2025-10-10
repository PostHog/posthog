import { useActions, useValues } from 'kea'

import { IconCopy, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationConditionSet } from '../types'

export function EvaluationTriggers(): JSX.Element {
    const { evaluation } = useValues(llmEvaluationLogic)
    const { setTriggerConditions } = useActions(llmEvaluationLogic)

    if (!evaluation) {
        return <div>Loading...</div>
    }

    const addConditionSet = (): void => {
        const newCondition: EvaluationConditionSet = {
            id: `cond-${Date.now()}`,
            rollout_percentage: 100,
            properties: [],
        }
        setTriggerConditions([...evaluation.conditions, newCondition])
    }

    const updateConditionSet = (index: number, updates: Partial<EvaluationConditionSet>): void => {
        const updatedConditions = evaluation.conditions.map((condition, i) =>
            i === index ? { ...condition, ...updates } : condition
        )
        setTriggerConditions(updatedConditions)
    }

    const removeConditionSet = (index: number): void => {
        if (evaluation.conditions.length === 1) {
            // Keep at least one condition set
            return
        }
        const updatedConditions = evaluation.conditions.filter((_, i) => i !== index)
        setTriggerConditions(updatedConditions)
    }

    const duplicateConditionSet = (index: number): void => {
        const conditionToDuplicate = evaluation.conditions[index]
        const duplicatedCondition: EvaluationConditionSet = {
            ...conditionToDuplicate,
            id: `cond-${Date.now()}`,
        }
        const updatedConditions = [...evaluation.conditions]
        updatedConditions.splice(index + 1, 0, duplicatedCondition)
        setTriggerConditions(updatedConditions)
    }

    return (
        <div className="space-y-6">
            <div className="text-sm text-muted">
                Each condition set below defines when this evaluation should trigger. If multiple condition sets exist,
                the evaluation will trigger if ANY of them match (OR logic).
            </div>

            {evaluation.conditions.map((condition, index) => (
                <div key={condition.id} className="bg-bg-light border rounded p-4 space-y-4">
                    {/* Header */}
                    <div className="flex justify-between items-center">
                        <div className="flex items-center gap-2">
                            <h4 className="font-semibold">Condition set {index + 1}</h4>
                            {evaluation.conditions.length > 1 && (
                                <div className="text-sm text-muted">{index === 0 ? 'IF' : 'OR IF'}</div>
                            )}
                        </div>
                        <div className="flex gap-1">
                            <LemonButton
                                icon={<IconCopy />}
                                size="small"
                                type="secondary"
                                onClick={() => duplicateConditionSet(index)}
                                tooltip="Duplicate condition set"
                            />
                            {evaluation.conditions.length > 1 && (
                                <LemonButton
                                    icon={<IconTrash />}
                                    size="small"
                                    type="secondary"
                                    status="danger"
                                    onClick={() => removeConditionSet(index)}
                                    tooltip="Remove condition set"
                                />
                            )}
                        </div>
                    </div>

                    {/* Percentage Control */}
                    <div className="space-y-2">
                        <label className="block text-sm font-medium">Sampling percentage</label>
                        <div className="flex items-center gap-4 max-w-md">
                            <div className="flex-1">
                                <LemonSlider
                                    value={condition.rollout_percentage}
                                    onChange={(value) => updateConditionSet(index, { rollout_percentage: value })}
                                    min={0.1}
                                    max={100}
                                    step={0.1}
                                />
                            </div>
                            <div className="w-20">
                                <LemonInput
                                    type="number"
                                    value={condition.rollout_percentage}
                                    onChange={(value) =>
                                        updateConditionSet(index, { rollout_percentage: Number(value) || 0.1 })
                                    }
                                    min={0.1}
                                    max={100}
                                    step={0.1}
                                    suffix={<span>%</span>}
                                />
                            </div>
                        </div>
                        <div className="text-xs text-muted">
                            This evaluation will run on {condition.rollout_percentage.toFixed(2)}% of matching
                            generations
                        </div>
                    </div>

                    {/* Property Filters */}
                    <div className="space-y-2">
                        <label className="block text-sm font-medium">Generation properties</label>
                        <div className="text-sm text-muted mb-2">
                            Define which generation events should trigger this evaluation. Leave empty to match all
                            generations.
                        </div>
                        <PropertyFilters
                            propertyFilters={condition.properties}
                            onChange={(properties) => updateConditionSet(index, { properties })}
                            pageKey={`evaluation-condition-${condition.id}`}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.EventMetadata,
                            ]}
                            addText="Add generation property condition"
                            hasRowOperator={false}
                            sendAllKeyUpdates
                            allowRelativeDateOptions={false}
                        />
                    </div>
                </div>
            ))}

            {/* Add Condition Set Button */}
            <div className="flex justify-center">
                <LemonButton type="secondary" icon={<IconPlus />} onClick={addConditionSet}>
                    Add Condition Set
                </LemonButton>
            </div>

            {/* Help Section */}
            <div className="bg-bg-light border rounded p-3 text-sm">
                <h4 className="font-semibold mb-2">Examples:</h4>
                <ul className="space-y-1 text-muted list-disc list-inside">
                    <li>
                        <strong>10% of all generations:</strong> Set 10% sampling with no property conditions
                    </li>
                    <li>
                        <strong>5% of GPT-4 generations:</strong> Set 5% sampling with $ai_model_name = "gpt-4"
                    </li>
                    <li>
                        <strong>20% of custom property generations:</strong> Set 20% sampling with my_custom_property =
                        "value"
                    </li>
                    <li>
                        <strong>High-cost generations:</strong> Set 100% sampling with $ai_total_cost_usd &gt; 0.01
                    </li>
                </ul>
            </div>
        </div>
    )
}
