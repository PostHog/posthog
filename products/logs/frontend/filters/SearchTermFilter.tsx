import { LemonInput } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { logsLogic } from '../logsLogic'

const NestedFilterValues = (): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <>
                        <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                            <NestedFilterValues />
                        </UniversalFilters.Group>
                    </>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        initiallyOpen={true}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                    />
                )
            })}
        </>
    )
}

export const SearchTermFilter = (): JSX.Element => {
    const { searchTerm } = useValues(logsLogic)
    const { setSearchTerm } = useActions(logsLogic)

    return (
        <span className="rounded bg-surface-primary">
            <LemonInput
                size="small"
                value={searchTerm}
                onChange={(value) => setSearchTerm(value)}
                placeholder="Search logs..."
                prefix={<NestedFilterValues />}
            />
        </span>
    )
}
