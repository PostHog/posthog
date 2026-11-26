import { BindLogic, useActions, useValues } from 'kea'
import { memo, useCallback, useMemo, useRef, useState } from 'react'

import { LemonDropdown } from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

const taxonomicFilterLogicKey = 'logs-alert'
const taxonomicGroupTypes = [
    TaxonomicFilterGroupType.Logs,
    TaxonomicFilterGroupType.LogResourceAttributes,
    TaxonomicFilterGroupType.LogAttributes,
]

export const AlertFilterGroup = memo(function AlertFilterGroup({
    filterGroup,
    onChange,
}: {
    filterGroup: UniversalFiltersGroup
    onChange: (group: UniversalFiltersGroup) => void
}): JSX.Element {
    const newlyAddedFilterIndex = useRef<number | null>(null)
    const markBlankFilterAsNew = useCallback((index: number): void => {
        newlyAddedFilterIndex.current = index
    }, [])

    return (
        <UniversalFilters
            rootKey={taxonomicFilterLogicKey}
            group={filterGroup}
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={onChange}
        >
            <div className="space-y-2">
                <AlertFilterSearch onAddBlankFilter={markBlankFilterAsNew} />
                <AlertAppliedFilters initiallyOpenFilterIndex={newlyAddedFilterIndex.current} />
            </div>
        </UniversalFilters>
    )
})

function AlertFilterSearch({ onAddBlankFilter }: { onAddBlankFilter: (index: number) => void }): JSX.Element {
    const [visible, setVisible] = useState<boolean>(false)
    const { addGroupFilter, setGroupValues } = useActions(universalFiltersLogic)
    const { filterGroup } = useValues(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)
    const filterGroupRef = useRef(filterGroup)
    filterGroupRef.current = filterGroup

    const onClose = useCallback((): void => {
        searchInputRef.current?.blur()
        setVisible(false)
    }, [])

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = useMemo(
        () => ({
            taxonomicFilterLogicKey,
            taxonomicGroupTypes,
            onChange: (taxonomicGroup, value, item) => {
                if (item.value === undefined) {
                    onAddBlankFilter(filterGroupRef.current.values.length)
                    addGroupFilter(taxonomicGroup, value, item)
                    setVisible(false)
                    return
                }

                const newValues = [...filterGroupRef.current.values]
                const newPropertyFilter = {
                    key: item.key,
                    value: item.value,
                    operator: PropertyOperator.IContains,
                    type: item.propertyFilterType,
                } as AnyPropertyFilter
                newValues.push(newPropertyFilter)
                setGroupValues(newValues)
                setVisible(false)
            },
            onEnter: () => {
                searchInputRef.current?.blur()
                setVisible(false)
            },
            autoSelectItem: true,
        }),
        [addGroupFilter, onAddBlankFilter, setGroupValues]
    )

    const showDropdown = useCallback(() => setVisible(true), [])

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                overlay={
                    <div className="w-[400px]">
                        <InfiniteSelectResults
                            focusInput={() => searchInputRef.current?.focus()}
                            taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                            popupAnchorElement={floatingRef.current}
                        />
                    </div>
                }
                visible={visible}
                closeOnClickInside={false}
                floatingRef={floatingRef}
                onClickOutside={onClose}
            >
                <TaxonomicFilterSearchInput
                    onClick={showDropdown}
                    searchInputRef={searchInputRef}
                    onClose={onClose}
                    onChange={showDropdown}
                    autoFocus={false}
                />
            </LemonDropdown>
        </BindLogic>
    )
}

function AlertAppliedFilters({
    initiallyOpenFilterIndex = null,
}: {
    initiallyOpenFilterIndex?: number | null
}): JSX.Element | null {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    if (filterGroup.values.length === 0) {
        return null
    }

    return (
        <div className="flex gap-1 items-center flex-wrap">
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                        <AlertAppliedFilters />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={
                            index === initiallyOpenFilterIndex && filterOrGroup.type !== PropertyFilterType.HogQL
                        }
                    />
                )
            })}
        </div>
    )
}
