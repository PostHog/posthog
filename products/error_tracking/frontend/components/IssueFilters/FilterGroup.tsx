import { BindLogic, useActions, useValues } from 'kea'
import { PropsWithChildren, ReactNode, useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSegmentedButton, Popover, PopoverReferenceContext } from '@posthog/lemon-ui'

import { quickFiltersLogic, quickFiltersSectionLogic } from 'lib/components/QuickFilters'
import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { cn } from 'lib/utils/css-classes'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { ErrorTrackingIssueAssignee, QuickFilterContext } from '~/queries/schema/schema-general'
import {
    FilterLogicalOperator,
    PropertyFilterType,
    QuickFilter,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { AssigneeLabelDisplay, AssigneeResolver } from '../Assignee/AssigneeDisplay'
import { AssigneeDropdown } from '../Assignee/AssigneeDropdown'
import { assigneeSelectLogic } from '../Assignee/assigneeSelectLogic'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { TAXONOMIC_FILTER_LOGIC_KEY, TAXONOMIC_GROUP_TYPES } from './consts'
import { issueFiltersLogic } from './issueFiltersLogic'
import { ErrorTrackingStatusSelectValue, STATUS_OPTIONS, statusOptionLabelWithDescription } from './Status'

export const FilterGroup = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    excludeFilterTypes,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    excludeFilterTypes?: PropertyFilterType[]
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
            <UniversalSearch taxonomicGroupTypes={taxonomicGroupTypes} />
        </UniversalFilters>
    )
}

const UniversalSearch = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
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
                <div className="min-w-0 flex-1">
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
                            prefix={<UniversalFilterGroup taxonomicGroupTypes={taxonomicGroupTypes} />}
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

export const FilterOperatorToggle = (): JSX.Element | null => {
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

export const UniversalFilterGroup = ({
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

export const FilterChip = ({
    onClear,
    overlay,
    children,
}: PropsWithChildren<{
    onClear: () => void
    /** When provided, clicking the chip body opens this editor in a popover below the chip. */
    overlay?: (close: () => void) => ReactNode
}>): JSX.Element => {
    const [open, setOpen] = useState<boolean>(false)
    const editable = !!overlay

    const chip = (
        <div
            className={cn('UniversalFilterButton UniversalFilterButton--closeable inline-flex items-center', {
                'UniversalFilterButton--clickable': editable,
            })}
        >
            <span
                className="UniversalFilterButton-content flex flex-1 items-center truncate gap-1"
                onClick={editable ? () => setOpen((o) => !o) : undefined}
            >
                {children}
            </span>
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

    if (!editable) {
        return chip
    }

    return (
        <Popover visible={open} onClickOutside={() => setOpen(false)} overlay={overlay(() => setOpen(false))}>
            {chip}
        </Popover>
    )
}

export const QuickFilterChips = ({
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

const StatusEditor = ({
    value,
    onChange,
}: {
    value: ErrorTrackingStatusSelectValue
    onChange: (value: ErrorTrackingStatusSelectValue) => void
}): JSX.Element => (
    <div className="flex flex-col gap-px min-w-[240px]">
        {STATUS_OPTIONS.map((option) => (
            <LemonButton
                key={option}
                fullWidth
                size="small"
                active={value === option}
                sideIcon={value === option ? <IconCheck /> : undefined}
                onClick={() => onChange(option)}
            >
                {statusOptionLabelWithDescription(option)}
            </LemonButton>
        ))}
    </div>
)

const AssigneeEditor = ({
    assignee,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    const { ensureAssigneeTypesLoaded, setSearch } = useActions(assigneeSelectLogic)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <AssigneeDropdown
            assignee={assignee}
            onChange={(value) => {
                setSearch('')
                onChange(value)
            }}
        />
    )
}

export const IssueFilterChips = (): JSX.Element | null => {
    const { status, assignee } = useValues(issueQueryOptionsLogic)
    const { setStatus, setAssignee } = useActions(issueQueryOptionsLogic)

    const resolvedStatus = status ?? 'active'
    const showStatus = resolvedStatus !== 'all'
    const showAssignee = !!assignee

    if (!showStatus && !showAssignee) {
        return null
    }

    return (
        <>
            {showStatus && (
                <FilterChip
                    onClear={() => setStatus('all')}
                    overlay={(close) => (
                        <StatusEditor
                            value={resolvedStatus}
                            onChange={(next) => {
                                setStatus(next)
                                close()
                            }}
                        />
                    )}
                >
                    Status is {capitalizeFirstLetter(resolvedStatus)}
                </FilterChip>
            )}
            {showAssignee && (
                <AssigneeResolver assignee={assignee}>
                    {({ assignee: resolvedAssignee }) => (
                        <FilterChip
                            onClear={() => setAssignee(null)}
                            overlay={(close) => (
                                <AssigneeEditor
                                    assignee={assignee}
                                    onChange={(value) => {
                                        setAssignee(value)
                                        close()
                                    }}
                                />
                            )}
                        >
                            Assignee is <AssigneeLabelDisplay assignee={resolvedAssignee} size="xsmall" />
                        </FilterChip>
                    )}
                </AssigneeResolver>
            )}
        </>
    )
}

export const InternalUsersChip = (): JSX.Element | null => {
    const { filterTestAccounts } = useValues(issueFiltersLogic)
    const { setFilterTestAccounts } = useActions(issueFiltersLogic)

    if (!filterTestAccounts) {
        return null
    }

    return <FilterChip onClear={() => setFilterTestAccounts(false)}>Internal users filtered</FilterChip>
}
