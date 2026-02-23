import { BindLogic, useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { LemonDropdown } from '@posthog/lemon-ui'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { TestAccountFilter } from 'scenes/insights/filters/TestAccountFilter'

import { FilterLogicalOperator, PropertyFilterType, UniversalFiltersGroup } from '~/types'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'

const TAXONOMIC_FILTER_LOGIC_KEY = 'insights-filters'
const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.ErrorTrackingProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.HogQLExpression,
]

export function InsightsFilters(): JSX.Element {
    const { filterGroup, filterTestAccounts } = useValues(errorTrackingInsightsLogic)
    const { setFilterGroup, setFilterTestAccounts } = useActions(errorTrackingInsightsLogic)

    return (
        <div className="flex gap-2 items-start">
            <div className="flex-1">
                <UniversalFilters
                    rootKey={TAXONOMIC_FILTER_LOGIC_KEY}
                    group={filterGroup.values[0] as UniversalFiltersGroup}
                    taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
                    onChange={(group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })}
                >
                    <FilterSearch />
                </UniversalFilters>
            </div>
            <TestAccountFilter
                size="small"
                filters={{ filter_test_accounts: filterTestAccounts }}
                onChange={({ filter_test_accounts }) => setFilterTestAccounts(filter_test_accounts || false)}
            />
        </div>
    )
}

function FilterSearch(): JSX.Element {
    const [visible, setVisible] = useState(false)
    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    const onClose = (): void => {
        searchInputRef.current?.blur()
        setVisible(false)
    }

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: TAXONOMIC_FILTER_LOGIC_KEY,
        taxonomicGroupTypes: TAXONOMIC_GROUP_TYPES,
        onChange: (taxonomicGroup, value, item, originalQuery) => {
            searchInputRef.current?.blur()
            setVisible(false)
            addGroupFilter(taxonomicGroup, value, item, originalQuery)
        },
        onEnter: onClose,
        autoSelectItem: false,
    }

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                overlay={
                    <div className="w-[400px] md:w-[600px]">
                        <InfiniteSelectResults
                            focusInput={() => searchInputRef.current?.focus()}
                            taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                            popupAnchorElement={floatingRef.current}
                            useVerticalLayout={true}
                        />
                    </div>
                }
                visible={visible}
                closeOnClickInside={false}
                floatingRef={floatingRef}
                onClickOutside={onClose}
            >
                <TaxonomicFilterSearchInput
                    prefix={<FilterChips />}
                    onClick={() => setVisible(true)}
                    searchInputRef={searchInputRef}
                    onClose={onClose}
                    size="small"
                    autoFocus={false}
                    fullWidth
                />
            </LemonDropdown>
        </BindLogic>
    )
}

function FilterChips(): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    return (
        <>
            {filterGroup.values.map((filterOrGroup, index) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                        <FilterSearch />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                        initiallyOpen={allowInitiallyOpen && filterOrGroup.type != PropertyFilterType.HogQL}
                    />
                )
            })}
        </>
    )
}
