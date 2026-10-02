import { IconClock, IconPeople } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { UniversalFilterButton } from 'lib/components/UniversalFilters/UniversalFilterButton'
import { isEntityFilter } from 'lib/components/UniversalFilters/utils'
import { humanFriendlyDurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import {
    deriveOperand,
    recordingsQueryToUniversalFilters,
} from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFilterValue } from '~/types'

/** One recording filter, read-only. An event or action filter carries its own property filters, which the
 * editable UI keeps behind a popover — there's nothing to open here, so show them alongside the event. */
function ReadonlyFilter({ filter }: { filter: UniversalFilterValue }): JSX.Element {
    const properties = isEntityFilter(filter) ? (filter.properties ?? []) : []
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            <UniversalFilterButton filter={filter} />
            {properties.length > 0 && (
                <>
                    <span className="text-xs">where</span>
                    {properties.map((property, i) => (
                        <PropertyFilterButton key={i} item={property} compact />
                    ))}
                </>
            )}
        </div>
    )
}

/** The recording filters a query selects on: events, actions, properties, console logs, duration, test accounts. */
export function ScannerRecordingFilters({ query }: { query: unknown }): JSX.Element {
    // Read every filter dimension, not just top-level properties.
    const universal = recordingsQueryToUniversalFilters((query ?? null) as RecordingsQuery | null)
    const filters = filtersFromUniversalFilterGroups(universal)
    if (filters.length === 0 && universal.duration.length === 0 && !universal.filter_test_accounts) {
        return <span className="text-muted">No filters</span>
    }
    const matchWord = deriveOperand(universal.filter_group) === FilterLogicalOperator.Or ? 'any' : 'all'
    return (
        <div className="flex flex-col gap-2">
            {filters.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                    {filters.length > 1 && <span className="text-xs">Match {matchWord} of</span>}
                    {filters.map((filter, i) => (
                        <ReadonlyFilter key={i} filter={filter} />
                    ))}
                </div>
            )}
            {(universal.duration.length > 0 || universal.filter_test_accounts) && (
                <div className="flex flex-wrap items-center gap-1.5">
                    {universal.duration.map((duration, i) => (
                        <LemonTag key={i} type="default" icon={<IconClock />}>
                            {humanFriendlyDurationFilter(duration, duration.key)}
                        </LemonTag>
                    ))}
                    {universal.filter_test_accounts && (
                        <LemonTag type="default" icon={<IconPeople />}>
                            No internal/test users
                        </LemonTag>
                    )}
                </div>
            )}
        </div>
    )
}
