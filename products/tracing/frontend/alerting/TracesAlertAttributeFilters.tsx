import { useActions, useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { dayjs } from 'lib/dayjs'

import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { SUGGESTION_RANGE } from './tracesAlertUtils'

const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.Spans,
    TaxonomicFilterGroupType.SpanAttributes,
    TaxonomicFilterGroupType.SpanResourceAttributes,
]

interface TracesAlertAttributeFiltersProps {
    /** In the tracing scene's shape: an AND group around one inner group of filters. */
    filterGroup: UniversalFiltersGroup
    serviceNames: string[]
    onChange: (filterGroup: UniversalFiltersGroup) => void
}

export function TracesAlertAttributeFilters({
    filterGroup,
    serviceNames,
    onChange,
}: TracesAlertAttributeFiltersProps): JSX.Element {
    const extraGroups = filterGroup.values.length - 1
    return (
        <UniversalFilters
            rootKey="traces-alert"
            group={filterGroup.values[0] as UniversalFiltersGroup}
            taxonomicGroupTypes={taxonomicGroupTypes}
            endpointFilters={{
                dateRange: { ...SUGGESTION_RANGE, date_to: dayjs().toISOString() },
                serviceNames,
            }}
            // Only the first group is editable here. An alert saved through the API may hold more, and they
            // keep applying, so an edit replaces the first and keeps the rest.
            onChange={(group) =>
                onChange({ type: FilterLogicalOperator.And, values: [group, ...filterGroup.values.slice(1)] })
            }
        >
            <div className="flex flex-wrap items-center gap-1">
                <FilterValues />
                <UniversalFilters.AddFilterButton size="small" type="secondary" data-attr="traces-alert-add-filter" />
            </div>
            {extraGroups > 0 ? (
                <p className="text-xs text-secondary m-0 mt-1">
                    Plus {extraGroups} more filter {extraGroups === 1 ? 'group' : 'groups'} set through the API, which
                    this form keeps but cannot edit.
                </p>
            ) : null}
        </UniversalFilters>
    )
}

function FilterValues(): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) =>
                isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                        <FilterValues />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                    />
                )
            )}
        </>
    )
}
