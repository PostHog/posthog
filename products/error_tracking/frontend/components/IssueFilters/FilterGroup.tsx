import { BindLogic, useActions, useValues } from 'kea'
import { PropsWithChildren, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSegmentedButton, PopoverReferenceContext } from '@posthog/lemon-ui'

import { quickFiltersLogic, quickFiltersSectionLogic } from 'lib/components/QuickFilters'
import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { capitalizeFirstLetter } from 'lib/utils'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    PropertyFilterType,
    QuickFilter,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { AssigneeLabelDisplay, AssigneeResolver } from '../Assignee/AssigneeDisplay'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { TAXONOMIC_FILTER_LOGIC_KEY, TAXONOMIC_GROUP_TYPES } from './consts'
import { issueFiltersLogic } from './issueFiltersLogic'

export const FilterGroup = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    excludeFilterTypes,
    quickFilterContext,
    logicKey,
    showIssueFilters = true,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    excludeFilterTypes?: PropertyFilterType[]
    quickFilterContext?: QuickFilterContext
    logicKey?: string
    showIssueFilters?: boolean
} = {}): JSX.Element => {
    const { filterGroup } = useValues(issueFiltersLogic)
    const { setFilterGroup } = useActions(issueFiltersLogic)

    const inner = filterGroup.values[0] as UniversalFiltersGroup
    const displayGroup =
        excludeFilterTypes && excludeFilterTypes.length > 0
            ? { ...inner, values: inner.values.filter((f: any) => !excludeFilterTypes.includes(f.type)) }
            : inner

    return (
        <UniversalFilters
            rootKey={TAXONOMIC_FILTER_LOGIC_KEY}
            group={displayGroup}
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={(group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] })}
        >
            <UniversalSearch
                taxonomicGroupTypes={taxonomicGroupTypes}
                quickFilterContext={quickFilterContext}
                logicKey={logicKey}
                showIssueFilters={showIssueFilters}
            />
        </UniversalFilters>
    )
}

const UniversalSearch = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    quickFilterContext,
    logicKey,
    showIssueFilters = true,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    quickFilterContext?: QuickFilterContext
    logicKey?: string
    showIssueFilters?: boolean
}): JSX.Element => {
    const [visible, setVisible] = useState<boolean>(false)
    const { searchQuery } = useValues(issueFiltersLogic)
    const { setSearchQuery } = useActions(issueFiltersLogic)
    const { addGroupFilter } = useActions(universalFiltersLogic)

    const searchInputRef = useRef<HTMLInputElement | null>(null)
    const floatingRef = useRef<HTMLDivElement | null>(null)

    const onClose = (): void => {
        searchInputRef.current?.blur()
        setVisible(false)
    }

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: TAXONOMIC_FILTER_LOGIC_KEY,
        taxonomicGroupTypes,
        onChange: (taxonomicGroup, value, item) => {
            searchInputRef.current?.blur()
            setVisible(false)
            setSearchQuery('')
            addGroupFilter(taxonomicGroup, value, item)
        },
        onEnter: onClose,
        autoSelectItem: false,
        initialSearchQuery: searchQuery,
        excludedProperties: { [TaxonomicFilterGroupType.ErrorTrackingIssues]: ['assignee'] },
    }

    const onChange = useDebouncedCallback((value: string) => setSearchQuery(value), 250)

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <div className="flex w-full min-w-0 items-center gap-1">
                <FilterOperatorToggle />
                <div className="min-w-0 flex-1 [&_.LemonInput>input]:pl-2">
                    <LemonDropdown
                        overlay={
                            <div className="w-[400px] md:w-[600px]">
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
                        onClickOutside={() => onClose()}
                    >
                        <TaxonomicFilterSearchInput
                            prefix={
                                <>
                                    {showIssueFilters && <IssueFilterChips />}
                                    <InternalUsersChip />
                                    {quickFilterContext && (
                                        <QuickFilterChips context={quickFilterContext} logicKey={logicKey} />
                                    )}
                                    <UniversalFilterGroup taxonomicGroupTypes={taxonomicGroupTypes} />
                                </>
                            }
                            onClick={() => setVisible(true)}
                            searchInputRef={searchInputRef}
                            onClose={() => onClose()}
                            onChange={onChange}
                            size="small"
                            autoFocus={false}
                            fullWidth
                            placeholder="Add a filter or search..."
                        />
                    </LemonDropdown>
                </div>
            </div>
        </BindLogic>
    )
}

const FILTER_LOGICAL_OPERATOR_OPTIONS = [
    {
        value: FilterLogicalOperator.And,
        label: 'All',
        tooltip: 'Match all filters',
    },
    {
        value: FilterLogicalOperator.Or,
        label: 'Any',
        tooltip: 'Match any filter',
    },
]

const FilterOperatorToggle = (): JSX.Element | null => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { setGroupType } = useActions(universalFiltersLogic)
    const showOperatorToggle = filterGroup.values.length > 1 || filterGroup.type === FilterLogicalOperator.Or

    if (!showOperatorToggle) {
        return null
    }

    return (
        <div className="shrink-0">
            <LemonSegmentedButton
                value={filterGroup.type}
                onChange={(type) => setGroupType(type)}
                options={FILTER_LOGICAL_OPERATOR_OPTIONS}
                size="xsmall"
            />
        </div>
    )
}

const UniversalFilterGroup = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
}): JSX.Element => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    return (
        <>
            {filterGroup.values.map((filterOrGroup: UniversalFiltersGroupValue, index: number) => {
                return isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                        <UniversalSearch taxonomicGroupTypes={taxonomicGroupTypes} />
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

const FilterChip = ({ onClear, children }: PropsWithChildren<{ onClear: () => void }>): JSX.Element => (
    <div className="UniversalFilterButton UniversalFilterButton--closeable inline-flex items-center">
        <span className="UniversalFilterButton-content flex flex-1 items-center truncate gap-1">{children}</span>
        <PopoverReferenceContext.Provider value={null}>
            <LemonButton
                size="xsmall"
                icon={<IconX className="w-3 h-3" />}
                onClick={(e) => {
                    e.stopPropagation()
                    onClear()
                }}
                className="p-0.5"
            />
        </PopoverReferenceContext.Provider>
    </div>
)

const QuickFilterChips = ({
    context,
    logicKey,
}: {
    context: QuickFilterContext
    logicKey?: string
}): JSX.Element | null => {
    const { quickFilters } = useValues(quickFiltersLogic({ context }))
    const { selectedQuickFilters } = useValues(quickFiltersSectionLogic({ context, logicKey }))
    const { clearQuickFilter } = useActions(quickFiltersSectionLogic({ context, logicKey }))

    const activeFilters = Object.values(selectedQuickFilters)
    if (activeFilters.length === 0) {
        return null
    }

    return (
        <>
            {activeFilters.map((selected) => {
                const filter = quickFilters.find((f: QuickFilter) => f.id === selected.filterId)
                const option = filter?.options.find((o) => o.id === selected.optionId)
                if (!filter || !option) {
                    return null
                }
                return (
                    <FilterChip key={selected.filterId} onClear={() => clearQuickFilter(selected.filterId)}>
                        {filter.name} is {option.label}
                    </FilterChip>
                )
            })}
        </>
    )
}

const IssueFilterChips = (): JSX.Element | null => {
    const { status, assignee } = useValues(issueQueryOptionsLogic)
    const { setStatus, setAssignee } = useActions(issueQueryOptionsLogic)

    const showStatus = status && status !== 'active'
    const showAssignee = !!assignee

    if (!showStatus && !showAssignee) {
        return null
    }

    return (
        <>
            {showStatus && (
                <FilterChip onClear={() => setStatus('active')}>Status is {capitalizeFirstLetter(status)}</FilterChip>
            )}
            {showAssignee && (
                <AssigneeResolver assignee={assignee}>
                    {({ assignee: resolvedAssignee }) => (
                        <FilterChip onClear={() => setAssignee(null)}>
                            Assignee is <AssigneeLabelDisplay assignee={resolvedAssignee} size="xsmall" />
                        </FilterChip>
                    )}
                </AssigneeResolver>
            )}
        </>
    )
}

const InternalUsersChip = (): JSX.Element | null => {
    const { filterTestAccounts } = useValues(issueFiltersLogic)
    const { setFilterTestAccounts } = useActions(issueFiltersLogic)

    if (!filterTestAccounts) {
        return null
    }

    return <FilterChip onClear={() => setFilterTestAccounts(false)}>Internal users filtered</FilterChip>
}
