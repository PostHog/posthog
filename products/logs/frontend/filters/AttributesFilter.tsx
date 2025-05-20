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
            taxonomicGroupTypes={[TaxonomicFilterGroupType.Logs]}
            onChange={(filterGroup) => {
                setFilterGroup(filterGroup)
            }}
        >
            <NestedFilterGroup rootKey={rootKey} />
        </UniversalFilters>
    )
}

const NestedFilterGroup = ({ rootKey }: { rootKey: string }): JSX.Element => {
    const { rootKey: currentKey, filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div className="border">
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <NestedFilterGroup rootKey={rootKey} />
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
            })}
            <UniversalFilters.AddFilterButton />
        </div>
    )
}
