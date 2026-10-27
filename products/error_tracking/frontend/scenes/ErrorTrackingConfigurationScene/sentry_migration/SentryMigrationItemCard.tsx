import { Badge, Card, CardContent, CardHeader, Checkbox, Label, Text } from '@posthog/quill'

import type { SentryMigrationFitEnumApi, SentryMigrationItemApi } from '../../../generated/api.schemas'
import { describeSuppressionFilters, formatRateLimit } from './sentryMigrationFormat'

const FIT_BADGES: Record<SentryMigrationFitEnumApi, { label: string; variant: 'success' | 'warning' | 'default' }> = {
    good: { label: 'Same behavior', variant: 'success' },
    partial: { label: 'Close match', variant: 'warning' },
    unsupported: { label: "Can't import", variant: 'default' },
}

export interface SentryMigrationItemCardProps {
    item: SentryMigrationItemApi
    selected: boolean
    disabledReason: string | null
    onToggle: () => void
}

export function SentryMigrationItemCard({
    item,
    selected,
    disabledReason,
    onToggle,
}: SentryMigrationItemCardProps): JSX.Element {
    const fitBadge = FIT_BADGES[item.fit]
    const checkboxId = `sentry-migration-${item.id}`
    const filters = item.suppression_rule_filters
    const filterRows = filters ? describeSuppressionFilters(filters) : []
    const builtInFilter = item.built_in_filter

    return (
        <Card size="sm">
            <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                        <Checkbox
                            id={checkboxId}
                            checked={selected}
                            onCheckedChange={onToggle}
                            disabledReason={disabledReason}
                            data-attr="error-tracking-sentry-migration-item"
                        />
                        <Label htmlFor={checkboxId}>{item.sentry_setting}</Label>
                    </div>
                    <div className="flex flex-wrap items-center gap-1">
                        {builtInFilter ? (
                            <Badge variant={item.already_in_posthog ? 'completed' : 'success'}>
                                {item.already_in_posthog ? 'Already on' : 'Built into PostHog'}
                            </Badge>
                        ) : (
                            <>
                                {item.already_in_posthog && <Badge variant="completed">Already in PostHog</Badge>}
                                <Badge variant={fitBadge.variant}>{fitBadge.label}</Badge>
                            </>
                        )}
                    </div>
                </div>
            </CardHeader>
            {builtInFilter ? (
                <CardContent className="flex flex-col gap-1">
                    <Text size="sm" className="m-0">
                        Turns on the <span className="font-medium">{builtInFilter.name}</span> rule
                    </Text>
                    <Text size="xs" variant="muted" className="m-0">
                        {builtInFilter.description}
                    </Text>
                    {builtInFilter.compared_with_sentry.length > 0 && (
                        <ul className="m-0 mt-1 flex list-disc flex-col gap-0.5 pl-4">
                            {builtInFilter.compared_with_sentry.map((point) => (
                                <li key={point} className="text-xs">
                                    {point}
                                </li>
                            ))}
                        </ul>
                    )}
                </CardContent>
            ) : (
                <CardContent className="flex flex-col gap-2">
                    <div className="flex flex-col gap-1">
                        <Text size="xs" variant="muted" weight="medium" className="m-0">
                            In Sentry
                        </Text>
                        <Text size="xs" className="m-0 break-all font-mono" translate="no">
                            {item.sentry_value}
                        </Text>
                    </div>
                    {item.rate_limit ? (
                        <div className="flex flex-col gap-1">
                            <Text size="xs" variant="muted" weight="medium" className="m-0">
                                Project rate limit in PostHog
                            </Text>
                            <Text size="xs" className="m-0" translate="no">
                                {formatRateLimit(item.rate_limit)}
                            </Text>
                        </div>
                    ) : filters && filterRows.length > 0 ? (
                        <div className="flex flex-col gap-1">
                            <Text size="xs" variant="muted" weight="medium" className="m-0">
                                Manual suppression rule in PostHog, matching {filters.type === 'OR' ? 'any' : 'all'} of
                            </Text>
                            {filterRows.map((row, index) => (
                                <Text key={index} size="xs" className="m-0 break-all">
                                    <span>{row.property}</span>{' '}
                                    <span className="text-muted-foreground">{row.operator}</span>{' '}
                                    <span className="font-mono" translate="no">
                                        {row.value}
                                    </span>
                                </Text>
                            ))}
                        </div>
                    ) : null}
                    {item.note && (
                        <Text size="xs" variant="muted" className="m-0">
                            {item.note}
                        </Text>
                    )}
                </CardContent>
            )}
        </Card>
    )
}
