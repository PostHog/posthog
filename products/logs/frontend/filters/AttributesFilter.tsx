import { useActions, useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { logsLogic } from '../logsLogic'

export const AttributesFilter = (): JSX.Element => {
    const { filterGroup } = useValues(logsLogic)
    const { setFilterGroup } = useActions(logsLogic)

    const rootKey = 'logs'

    return (
        <UniversalFilters
            rootKey={rootKey}
            group={filterGroup}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.LogAttributes]}
            onChange={(filterGroup) => setFilterGroup(filterGroup)}
        >
            <NestedFilterGroup />
        </UniversalFilters>
    )
}

const NestedFilterGroup = (): JSX.Element => {
    const { openFilterOnInsert } = useValues(logsLogic)
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div className="flex gap-1 items-center flex-wrap">
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <>
                        <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                            <UniversalFilters.AddFilterButton
                                className="bg-surface-primary"
                                size="small"
                                type="secondary"
                            />
                            <NestedFilterGroup />
                        </UniversalFilters.Group>
                    </>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        initiallyOpen={openFilterOnInsert}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        className="h-[33px]"
                    />
                )
            })}
        </div>
    )
}
