import type { ReactElement } from 'react'

import { formatDate } from '@posthog/mcp-ui'
import { Badge, Card, CardContent, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@posthog/quill'

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
        <TooltipProvider>
            <div className="p-4">
                <div className="flex flex-col gap-3">
                    {/* Header */}
                    <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-lg font-semibold">{flag.key}</span>
                            <Badge variant={flag.active ? 'success' : 'default'}>
                                {flag.active ? 'Active' : 'Inactive'}
                            </Badge>
                        </div>
                        {flag.name && <span className="text-sm text-muted-foreground">{flag.name}</span>}
                        {flag.description && <span className="text-sm text-muted-foreground">{flag.description}</span>}
                        {(flag.tags?.length || flag.updated_at) && (
                            <div className="flex items-center gap-2 flex-wrap">
                                {flag.tags?.map((tag) => (
                                    <Badge key={tag}>{tag}</Badge>
                                ))}
                                {flag.updated_at && (
                                    <span className="text-xs text-muted-foreground">
                                        Last updated {formatDate(flag.updated_at, true)}
                                    </span>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Variants */}
                    {isMultivariate && (
                        <Card>
                            <CardContent>
                                <div className="flex flex-col gap-2">
                                    <span className="text-sm font-semibold">Variants</span>
                                    <VariantTable variants={variants} />
                                </div>
                            </CardContent>
                        </Card>
                    )}

                    {/* Release conditions */}
                    {groups.length > 0 && (
                        <Card>
                            <CardContent>
                                <div className="flex flex-col gap-3">
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <span className="text-sm font-semibold cursor-default border-b border-dashed border-muted-foreground self-start">
                                                    Release conditions
                                                </span>
                                            }
                                        />
                                        <TooltipContent side="bottom">
                                            Rules that determine which users see this flag
                                        </TooltipContent>
                                    </Tooltip>
                                    {groups.map((group, i) => {
                                        const isCatchAll = group.properties.length === 0 && groups.length > 1

                                        return (
                                            <div key={i} className="flex flex-col gap-2">
                                                {i > 0 && <div className="border-t -mx-4 mb-1" />}
                                                {groups.length > 1 && (
                                                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
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
                                                        <span className="text-xs text-muted-foreground">
                                                            Variant override:
                                                        </span>
                                                        <Badge variant="info">{group.variant}</Badge>
                                                    </div>
                                                )}
                                                {group.properties.length > 0 && (
                                                    <PropertyFilterList
                                                        filters={group.properties as PropertyFilter[]}
                                                    />
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                            </CardContent>
                        </Card>
                    )}
                </div>
            </div>
        </TooltipProvider>
    )
}
