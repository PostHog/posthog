import type { ReactElement } from 'react'

import { Badge, Card, Stack } from '@posthog/mosaic'

import { PropertyFilterList, type PropertyFilter } from './PropertyFilterList'

export interface ConditionAnalysis {
    index: number
    matched: boolean
    rollout_percentage: number
    variant?: string | null
    properties?: Array<{ key: string; value: unknown; operator?: string; type?: string }>
    reason?: string
    explanation?: string
}

export interface FeatureFlagTestEvaluationResult {
    flag_key: string
    result: boolean | string
    reason: string
    condition_index: number | null
    payload: unknown | null
    person_properties: Record<string, unknown>
    conditions: ConditionAnalysis[]
}

// Keep the original name for backward compatibility with the generated UI app
export type FeatureFlagTestingData = FeatureFlagTestEvaluationResult

export interface FeatureFlagTestingViewProps {
    flag: FeatureFlagTestingData
}

export function FeatureFlagTestingView({ flag }: FeatureFlagTestingViewProps): ReactElement {
    const getResultBadgeVariant = (): 'success' | 'danger' | 'info' => {
        if (typeof flag.result === 'boolean') {
            return flag.result ? 'success' : 'danger'
        }
        return 'info'
    }

    const formatResult = (): string => {
        if (typeof flag.result === 'boolean') {
            return flag.result ? 'True' : 'False'
        }
        return String(flag.result)
    }

    return (
        <div className="p-4">
            <Stack gap="md">
                {/* Header */}
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold text-text-primary">{flag.flag_key}</span>
                        <Badge variant="neutral" size="md">
                            Test Result
                        </Badge>
                    </div>
                    <span className="text-sm text-text-secondary">
                        Feature flag evaluation result for the tested user
                    </span>
                </Stack>

                {/* Evaluation Result */}
                <Card>
                    <Stack gap="sm">
                        <span className="font-medium text-text-primary">Test Evaluation Results</span>
                        <span className="text-sm text-text-secondary">
                            This shows how the flag evaluated for the specified user, including which condition matched
                            and the person properties that were considered.
                        </span>
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">Result:</span>
                            <Badge variant={getResultBadgeVariant()} size="md">
                                {formatResult()}
                            </Badge>
                        </div>
                        <div className="text-sm">
                            <span className="font-medium">Reason: </span>
                            <span className="text-text-secondary">{flag.reason}</span>
                        </div>
                        {flag.condition_index !== null && (
                            <div className="text-sm">
                                <span className="font-medium">Matched condition: </span>
                                <span className="text-text-secondary">#{flag.condition_index + 1}</span>
                            </div>
                        )}
                        {flag.payload != null && (
                            <div className="text-sm">
                                <span className="font-medium">Payload: </span>
                                <code className="text-xs bg-bg-light p-1 rounded">
                                    {JSON.stringify(flag.payload) || 'null'}
                                </code>
                            </div>
                        )}
                    </Stack>
                </Card>

                {/* Person Properties */}
                {Object.keys(flag.person_properties).length > 0 && (
                    <Card>
                        <Stack gap="sm">
                            <span className="font-medium text-text-primary">Person Properties</span>
                            <div className="space-y-1">
                                {Object.entries(flag.person_properties).map(([key, value]) => (
                                    <div key={key} className="flex items-center gap-2 text-sm">
                                        <span className="font-mono text-text-primary">{key}:</span>
                                        <span className="text-text-secondary">
                                            {typeof value === 'object' ? String(JSON.stringify(value)) : String(value)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </Stack>
                    </Card>
                )}

                {/* Condition Analysis */}
                {flag.conditions.length > 0 && (
                    <Card>
                        <Stack gap="sm">
                            <span className="font-medium text-text-primary">Condition Analysis</span>
                            <span className="text-sm text-text-secondary">
                                Detailed breakdown of how each condition was evaluated
                            </span>
                            <Stack gap="sm">
                                {flag.conditions.map((condition, index) => (
                                    <Card key={index}>
                                        <Stack gap="xs">
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-medium">
                                                    Condition #{condition.index + 1}
                                                </span>
                                                <Badge variant={condition.matched ? 'success' : 'danger'} size="sm">
                                                    {condition.matched ? 'Matched' : 'No match'}
                                                </Badge>
                                                <Badge variant="neutral" size="sm">
                                                    {condition.rollout_percentage}% rollout
                                                </Badge>
                                                {condition.variant && (
                                                    <Badge variant="info" size="sm">
                                                        {condition.variant}
                                                    </Badge>
                                                )}
                                            </div>
                                            {(condition.explanation || condition.reason) && (
                                                <div className="text-sm text-text-secondary">
                                                    {condition.explanation || condition.reason}
                                                </div>
                                            )}
                                            {condition.properties && condition.properties.length > 0 && (
                                                <PropertyFilterList
                                                    filters={condition.properties as PropertyFilter[]}
                                                />
                                            )}
                                        </Stack>
                                    </Card>
                                ))}
                            </Stack>
                        </Stack>
                    </Card>
                )}
            </Stack>
        </div>
    )
}
