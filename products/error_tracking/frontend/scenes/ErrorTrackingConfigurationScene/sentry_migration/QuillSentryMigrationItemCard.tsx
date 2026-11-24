import { Badge, Card, CardContent, CardHeader, Checkbox, Text } from '@posthog/quill'

import type { SentryMigrationFitEnumApi } from '../../../generated/api.schemas'
import { FIT_LABELS, describeSuppressionFilters, formatRateLimit } from './sentryMigrationFormat'
import type { SentryMigrationItemCardProps } from './SentryMigrationItemCard'

const FIT_BADGE_VARIANTS: Record<SentryMigrationFitEnumApi, 'success' | 'warning' | 'default'> = {
    good: 'success',
    partial: 'warning',
    unsupported: 'default',
}

export function QuillSentryMigrationItemCard({
    item,
    selected,
    disabledReason,
    onToggle,
}: SentryMigrationItemCardProps): JSX.Element {
    const filters = item.suppression_rule_filters
    const filterRows = filters ? describeSuppressionFilters(filters) : []
    const builtInFilter = item.built_in_filter

    return (
        <Card size="sm">
            <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Checkbox
                        checked={selected}
                        onCheckedChange={onToggle}
                        disabledReason={disabledReason}
                        data-attr="error-tracking-sentry-migration-item"
                    >
                        {item.sentry_setting}
                    </Checkbox>
                    <div className="flex flex-wrap items-center gap-1">
                        {builtInFilter ? (
                            item.already_in_posthog && <Badge variant="completed">Already on</Badge>
                        ) : (
                            <>
                                {item.already_in_posthog && <Badge variant="completed">Already in PostHog</Badge>}
                                <Badge variant={FIT_BADGE_VARIANTS[item.fit]}>{FIT_LABELS[item.fit]}</Badge>
                            </>
                        )}
                    </div>
                </div>
            </CardHeader>
            {builtInFilter ? (
                <CardContent className="flex flex-col gap-1">
                    <Text size="xs" render={<p className="m-0" />}>
                        Turns on the <span className="font-semibold">{builtInFilter.name}</span> rule
                    </Text>
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {builtInFilter.description}
                    </Text>
                    {builtInFilter.compared_with_sentry.length > 0 && (
                        <ul className="m-0 flex list-disc flex-col gap-0.5 pl-4">
                            {builtInFilter.compared_with_sentry.map((point) => (
                                <Text key={point} size="xs" render={<li />}>
                                    {point}
                                </Text>
                            ))}
                        </ul>
                    )}
                </CardContent>
            ) : (
                <CardContent className="flex flex-col gap-2">
                    <div className="flex flex-col gap-0.5">
                        <Text size="xs" variant="muted" weight="semibold" render={<span />}>
                            In Sentry
                        </Text>
                        <Text size="xs" className="break-all font-mono" render={<span translate="no" />}>
                            {item.sentry_value}
                        </Text>
                    </div>
                    {item.rate_limit ? (
                        <div className="flex flex-col gap-0.5">
                            <Text size="xs" variant="muted" weight="semibold" render={<span />}>
                                Project rate limit in PostHog
                            </Text>
                            <Text size="xs" render={<span translate="no" />}>
                                {formatRateLimit(item.rate_limit)}
                            </Text>
                        </div>
                    ) : filters && filterRows.length > 0 ? (
                        <div className="flex flex-col gap-0.5">
                            <Text size="xs" variant="muted" weight="semibold" render={<span />}>
                                Manual suppression rule in PostHog, matching {filters.type === 'OR' ? 'any' : 'all'} of
                            </Text>
                            {filterRows.map((row, index) => (
                                <Text key={index} size="xs" className="break-all" render={<span />}>
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
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {item.note}
                        </Text>
                    )}
                </CardContent>
            )}
        </Card>
    )
}
