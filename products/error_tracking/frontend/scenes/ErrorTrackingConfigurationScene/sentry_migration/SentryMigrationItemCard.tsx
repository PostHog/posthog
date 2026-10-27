import { LemonCheckbox, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import type { SentryMigrationFitEnumApi, SentryMigrationItemApi } from '../../../generated/api.schemas'
import { describeSuppressionFilters, formatRateLimit } from './sentryMigrationFormat'

const FIT_TAGS: Record<SentryMigrationFitEnumApi, { label: string; type: LemonTagType }> = {
    good: { label: 'Same behavior', type: 'success' },
    partial: { label: 'Close match', type: 'warning' },
    unsupported: { label: "Can't import", type: 'muted' },
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
    const fitTag = FIT_TAGS[item.fit]
    const filters = item.suppression_rule_filters
    const filterRows = filters ? describeSuppressionFilters(filters) : []
    const builtInFilter = item.built_in_filter

    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <LemonCheckbox
                    checked={selected}
                    onChange={onToggle}
                    disabledReason={disabledReason}
                    label={item.sentry_setting}
                    labelClassName="font-semibold"
                    data-attr="error-tracking-sentry-migration-item"
                />
                <div className="flex flex-wrap items-center gap-1">
                    {builtInFilter ? (
                        <LemonTag type={item.already_in_posthog ? 'completion' : 'success'}>
                            {item.already_in_posthog ? 'Already on' : 'Built into PostHog'}
                        </LemonTag>
                    ) : (
                        <>
                            {item.already_in_posthog && <LemonTag type="completion">Already in PostHog</LemonTag>}
                            <LemonTag type={fitTag.type}>{fitTag.label}</LemonTag>
                        </>
                    )}
                </div>
            </div>
            {builtInFilter ? (
                <div className="flex flex-col gap-1 pl-6">
                    <p className="text-sm mb-0">
                        Turns on the <span className="font-semibold">{builtInFilter.name}</span> rule
                    </p>
                    <p className="text-xs text-secondary mb-0">{builtInFilter.description}</p>
                    {builtInFilter.compared_with_sentry.length > 0 && (
                        <ul className="list-disc pl-4 mb-0 flex flex-col gap-0.5">
                            {builtInFilter.compared_with_sentry.map((point) => (
                                <li key={point} className="text-xs">
                                    {point}
                                </li>
                            ))}
                        </ul>
                    )}
                </div>
            ) : (
                <div className="flex flex-col gap-2 pl-6">
                    <div className="flex flex-col gap-0.5">
                        <span className="text-xs font-semibold text-secondary">In Sentry</span>
                        <span className="text-xs font-mono break-all" translate="no">
                            {item.sentry_value}
                        </span>
                    </div>
                    {item.rate_limit ? (
                        <div className="flex flex-col gap-0.5">
                            <span className="text-xs font-semibold text-secondary">Project rate limit in PostHog</span>
                            <span className="text-xs" translate="no">
                                {formatRateLimit(item.rate_limit)}
                            </span>
                        </div>
                    ) : filters && filterRows.length > 0 ? (
                        <div className="flex flex-col gap-0.5">
                            <span className="text-xs font-semibold text-secondary">
                                Manual suppression rule in PostHog, matching {filters.type === 'OR' ? 'any' : 'all'} of
                            </span>
                            {filterRows.map((row, index) => (
                                <span key={index} className="text-xs break-all">
                                    <span>{row.property}</span> <span className="text-secondary">{row.operator}</span>{' '}
                                    <span className="font-mono" translate="no">
                                        {row.value}
                                    </span>
                                </span>
                            ))}
                        </div>
                    ) : null}
                    {item.note && <p className="text-xs text-secondary mb-0">{item.note}</p>}
                </div>
            )}
        </div>
    )
}
