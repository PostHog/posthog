import type { ReactElement } from 'react'

import { Badge, Card, formatDate, Stack } from '@posthog/mosaic'

import { PropertyFilterList, type PropertyFilter } from './PropertyFilterList'

export interface FeatureFlagTestingData {
    id: number
    key: string
    name: string
    description?: string | null
    active: boolean
    filters?: {
        groups: Array<{
            properties: Array<{ key: string; value: unknown; operator?: string; type?: string }>
            rollout_percentage: number
            variant?: string | null
        }>
        multivariate?: {
            variants: Array<{ key: string; name?: string; rollout_percentage: number }>
        }
    }
    tags?: string[]
    updated_at?: string | null
    _posthogUrl?: string
}

export interface FeatureFlagTestingViewProps {
    flag: FeatureFlagTestingData
}

export function FeatureFlagTestingView({ flag }: FeatureFlagTestingViewProps): ReactElement {
    const groups = flag.filters?.groups ?? []

    return (
        <div className="p-4">
            <Stack gap="md">
                {/* Header */}
                <Stack gap="xs">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-lg font-semibold text-text-primary">{flag.key}</span>
                        <Badge variant={flag.active ? 'success' : 'neutral'} size="md">
                            {flag.active ? 'Active' : 'Inactive'}
                        </Badge>
                    </div>
                    {flag.name && <span className="text-sm text-text-secondary">{flag.name}</span>}
                    {flag.description && <span className="text-sm text-text-secondary">{flag.description}</span>}
                </Stack>

                {/* Testing Information */}
                <Card>
                    <Stack gap="sm">
                        <span className="font-medium text-text-primary">Flag Testing</span>
                        <span className="text-sm text-text-secondary">
                            Use the feature flag test evaluation tool to test how this flag evaluates for specific
                            users. The testing provides detailed analysis of condition matching and person properties.
                        </span>

                        {/* Show current conditions for reference */}
                        {groups.length > 0 && (
                            <div>
                                <span className="text-sm font-medium text-text-primary mb-2 block">
                                    Current conditions ({groups.length} group{groups.length !== 1 ? 's' : ''})
                                </span>
                                <Stack gap="sm">
                                    {groups.map((group, index) => (
                                        <Card key={index}>
                                            <Stack gap="xs">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-sm font-medium">Condition #{index + 1}</span>
                                                    <Badge variant="neutral" size="sm">
                                                        {group.rollout_percentage}% rollout
                                                    </Badge>
                                                    {group.variant && (
                                                        <Badge variant="info" size="sm">
                                                            {group.variant}
                                                        </Badge>
                                                    )}
                                                </div>
                                                {group.properties && group.properties.length > 0 && (
                                                    <PropertyFilterList
                                                        filters={group.properties as PropertyFilter[]}
                                                    />
                                                )}
                                            </Stack>
                                        </Card>
                                    ))}
                                </Stack>
                            </div>
                        )}

                        {groups.length === 0 && (
                            <div className="text-sm text-text-secondary">
                                This flag has no targeting conditions and will evaluate based on global rollout
                                settings.
                            </div>
                        )}
                    </Stack>
                </Card>

                {/* Metadata */}
                {flag.tags && flag.tags.length > 0 && (
                    <Card>
                        <Stack gap="sm">
                            <span className="font-medium text-text-primary">Tags</span>
                            <div className="flex gap-1 flex-wrap">
                                {flag.tags.map((tag) => (
                                    <Badge key={tag} variant="neutral" size="sm">
                                        {tag}
                                    </Badge>
                                ))}
                            </div>
                        </Stack>
                    </Card>
                )}

                {flag.updated_at && (
                    <span className="text-xs text-text-tertiary">Last updated: {formatDate(flag.updated_at)}</span>
                )}
            </Stack>
        </div>
    )
}
