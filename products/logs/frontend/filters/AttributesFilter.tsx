import { useValues } from 'kea'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

export const AttributesFilter = (): JSX.Element => {
    return <NestedFilterGroup addButton={false} />
}

type NestedFilterGroupProps = {
    addButton?: boolean
}

const NestedFilterGroup = ({ addButton }: NestedFilterGroupProps): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)

    return (
        <div>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <>
                        <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                            <NestedFilterGroup addButton={true} />
                        </UniversalFilters.Group>
                    </>
                ) : null
            })}
            {addButton ? (
                <UniversalFilters.AddFilterButton
                    className="rounded bg-surface-primary"
                    size="small"
                    type="secondary"
                />
            ) : null}
        </div>
    )
}
