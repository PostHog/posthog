import type { ReactElement } from 'react'

import { Badge, Card, formatDate, Stack, Tooltip } from '@posthog/mosaic'

import { PropertyFilterList, type PropertyFilter } from './PropertyFilterList'
import { RolloutBar } from './RolloutBar'
import { VariantTable, type Variant } from './VariantTable'

export interface FeatureFlagData {
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

export interface FeatureFlagViewProps {
    flag: FeatureFlagData
}

export function FeatureFlagView({ flag }: FeatureFlagViewProps): ReactElement {
    const groups = flag.filters?.groups ?? []
    const variants = flag.filters?.multivariate?.variants as Variant[] | undefined
    const isMultivariate = variants && variants.length > 0

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
                    {(flag.tags?.length || flag.updated_at) && (
                        <div className="flex items-center gap-2 flex-wrap">
                            {flag.tags?.map((tag) => (
                                <Badge key={tag} variant="neutral" size="sm">
                                    {tag}
                                </Badge>
                            ))}
                            {flag.updated_at && (
                                <span className="text-xs text-text-secondary">
                                    Last updated {formatDate(flag.updated_at, true)}
                                </span>
                            )}
                        </div>
                    )}
                </Stack>

                {/* Variants */}
                {isMultivariate && (
                    <Card padding="md">
                        <Stack gap="sm">
                            <span className="text-sm font-semibold text-text-primary">Variants</span>
                            <VariantTable variants={variants} />
                        </Stack>
                    </Card>
                )}

                {/* Release conditions */}
                {groups.length > 0 && (
                    <Card padding="md">
                        <Stack gap="md">
                            <Tooltip content="Rules that determine which users see this flag" position="bottom">
                                <span className="text-sm font-semibold text-text-primary cursor-default border-b border-dashed border-text-secondary">
                                    Release conditions
                                </span>
                            </Tooltip>
                            {groups.map((group, i) => {
                                const isCatchAll = group.properties.length === 0 && groups.length > 1

                                return (
                                    <Stack key={i} gap="sm">
                                        {i > 0 && <div className="border-t border-border-primary -mx-4 mb-1" />}
                                        {groups.length > 1 && (
                                            <span className="text-xs font-medium text-text-secondary uppercase tracking-wide">
                                                {isCatchAll ? 'Else (everyone)' : `Set ${i + 1}`}
                                            </span>
                                        )}
                                        <RolloutBar
                                            percentage={group.rollout_percentage}
                                            tooltip={
                                                isCatchAll
                                                    ? `${group.rollout_percentage}% of all remaining users`
                                                    : group.variant
                                                      ? `${group.rollout_percentage}% of matching users will get ${group.variant}`
                                                      : isMultivariate
                                                        ? 'Percentage of users matching these conditions'
                                                        : `${group.rollout_percentage}% of matching users will see this flag`
                                            }
                                        />
                                        {group.variant && (
                                            <div className="flex items-center gap-1">
                                                <span className="text-xs text-text-secondary">Variant override:</span>
                                                <Badge variant="info" size="sm">
                                                    {group.variant}
                                                </Badge>
                                            </div>
                                        )}
                                        {group.properties.length > 0 && (
                                            <PropertyFilterList filters={group.properties as PropertyFilter[]} />
                                        )}
                                    </Stack>
                                )
                            })}
                        </Stack>
                    </Card>
                )}
            </Stack>
        </div>
    )
}
