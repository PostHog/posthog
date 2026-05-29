import type { ReactElement } from 'react'

import { Badge, Card, CardContent, CardHeader, CardTitle, CardDescription } from '@posthog/quill'

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
    const getResultBadgeVariant = (): 'success' | 'destructive' | 'info' => {
        if (typeof flag.result === 'boolean') {
            return flag.result ? 'success' : 'destructive'
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
            <div className="flex flex-col gap-2">
                {/* Header */}
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold text-primary">{flag.flag_key}</span>
                        <Badge>Test Result</Badge>
                    </div>
                    <span className="text-sm text-secondary">Feature flag evaluation result for the tested user</span>
                </div>

                {/* Evaluation Result */}
                <Card>
                    <CardHeader>
                        <CardTitle>Test Evaluation Results</CardTitle>
                        <CardDescription>
                            This shows how the flag evaluated for the specified user, including which condition matched
                            and the person properties that were considered.
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        <div className="flex items-center gap-2">
                            <span className="text-sm font-medium">Result:</span>
                            <Badge variant={getResultBadgeVariant()}>{formatResult()}</Badge>
                        </div>
                        <div className="text-sm">
                            <span className="font-medium">Reason: </span>
                            <span className="text-secondary">{flag.reason}</span>
                        </div>
                        {flag.condition_index !== null && (
                            <div className="text-sm">
                                <span className="font-medium">Matched condition: </span>
                                <span className="text-secondary">#{flag.condition_index + 1}</span>
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
                    </CardContent>
                    <div className="p-1 flex flex-col gap-1" />
                </Card>

                {/* Person Properties */}
                {Object.keys(flag.person_properties).length > 0 && (
                    <Card>
                        <CardHeader>
                            <CardTitle>Person Properties</CardTitle>{' '}
                        </CardHeader>
                        <CardContent>
                            <div className="space-y-1">
                                {Object.entries(flag.person_properties).map(([key, value]) => (
                                    <div key={key} className="flex items-center gap-2 text-sm">
                                        <span className="font-mono text-primary">{key}:</span>
                                        <span className="text-secondary">
                                            {typeof value === 'object' ? String(JSON.stringify(value)) : String(value)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                )}

                {/* Condition Analysis */}
                {flag.conditions.length > 0 && (
                    <Card>
                        <CardHeader>
                            <CardTitle>Condition Analysis</CardTitle>
                            <CardDescription>Detailed breakdown of how each condition was evaluated</CardDescription>
                        </CardHeader>
                        <CardContent>
                            <div className="flex flex-col gap-1">
                                {flag.conditions.map((condition, index) => (
                                    <Card key={index}>
                                        <CardContent>
                                            <div className="flex items-center gap-2">
                                                <span className="text-sm font-medium">Condition #{index + 1}:</span>
                                                <Badge variant={condition.matched ? 'success' : 'destructive'}>
                                                    {condition.matched ? 'Matched' : 'No match'}
                                                </Badge>
                                                <Badge>{condition.rollout_percentage}% rollout</Badge>
                                                {condition.variant && <Badge variant="info">{condition.variant}</Badge>}
                                            </div>
                                            {(condition.explanation || condition.reason) && (
                                                <div className="text-sm text-secondary">
                                                    {condition.explanation || condition.reason}
                                                </div>
                                            )}
                                            {condition.properties && condition.properties.length > 0 && (
                                                <PropertyFilterList
                                                    filters={condition.properties as PropertyFilter[]}
                                                />
                                            )}
                                        </CardContent>
                                    </Card>
                                ))}
                            </div>
                        </CardContent>
                    </Card>
                )}
            </div>
        </div>
    )
}
