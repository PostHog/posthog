import { LemonCard, LemonCheckbox, LemonDivider, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { AnyPropertyFilter } from '~/types'

import type { SentryMigrationFitEnumApi, SentryMigrationItemApi } from '../../../generated/api.schemas'

const FIT_TAGS: Record<SentryMigrationFitEnumApi, { label: string; type: LemonTagType }> = {
    good: { label: 'Same behavior', type: 'success' },
    partial: { label: 'Close match', type: 'warning' },
    unsupported: { label: "Can't import", type: 'muted' },
}

function bucketLabel(minutes: number): string {
    return minutes % 60 === 0 ? `${minutes / 60} ${minutes === 60 ? 'hour' : 'hours'}` : `${minutes} minutes`
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
    const filters = (item.suppression_rule_filters?.values ?? []) as AnyPropertyFilter[]

    return (
        <LemonCard hoverEffect={false} className="flex flex-col p-0">
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
                <LemonCheckbox
                    checked={selected}
                    onChange={onToggle}
                    disabledReason={disabledReason}
                    label={item.sentry_setting}
                    data-attr="error-tracking-sentry-migration-item"
                />
                <div className="flex flex-wrap items-center gap-1">
                    {item.already_in_posthog && <LemonTag type="muted">Already in PostHog</LemonTag>}
                    <LemonTag type={fitTag.type}>{fitTag.label}</LemonTag>
                </div>
            </div>
            <LemonDivider className="my-0" />
            <div className="flex flex-col gap-2 px-3 py-2">
                <div className="flex flex-col gap-1">
                    <span className="text-xs font-semibold uppercase text-secondary">In Sentry</span>
                    <code className="break-all text-sm" translate="no">
                        {item.sentry_value}
                    </code>
                </div>
                {item.rate_limit ? (
                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-semibold uppercase text-secondary">
                            Project rate limit in PostHog
                        </span>
                        <span className="text-sm" translate="no">
                            {item.rate_limit.value.toLocaleString()} exceptions per{' '}
                            {bucketLabel(item.rate_limit.bucket_size_minutes)}
                        </span>
                    </div>
                ) : filters.length > 0 ? (
                    <div className="flex flex-col gap-1">
                        <span className="text-xs font-semibold uppercase text-secondary">
                            Suppression rule in PostHog, match{' '}
                            {item.suppression_rule_filters?.type === 'OR' ? 'any' : 'all'}
                        </span>
                        <PropertyFilters
                            editable={false}
                            propertyFilters={filters}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.ErrorTrackingProperties,
                                TaxonomicFilterGroupType.EventProperties,
                            ]}
                            onChange={() => {}}
                            pageKey={`sentry-migration-${item.id}`}
                            buttonSize="small"
                        />
                    </div>
                ) : null}
                {item.note && <p className="text-secondary text-xs m-0">{item.note}</p>}
            </div>
        </LemonCard>
    )
}
