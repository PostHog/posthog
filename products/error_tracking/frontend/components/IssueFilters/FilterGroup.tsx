import { BindLogic, useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { LemonSegmentedButton } from '@posthog/lemon-ui'
import { Popover, PopoverContent } from '@posthog/quill'

import { InfiniteSelectResults } from 'lib/components/TaxonomicFilter/InfiniteSelectResults'
import { TaxonomicFilterSearchInput } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { FilterLogicalOperator, PropertyFilterType, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

import { TAXONOMIC_FILTER_LOGIC_KEY, TAXONOMIC_GROUP_TYPES } from './consts'
import { issueFiltersLogic } from './issueFiltersLogic'

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
    const anchorRef = useRef<HTMLDivElement | null>(null)
    const popupRef = useRef<HTMLDivElement | null>(null)

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

    // Manual outside-click handling. base-ui Popover's automatic outside-press
    // dismiss is unreliable when the anchor isn't a real PopoverTrigger, so we
    // cancel its firings (except Escape) in onOpenChange and close here instead.
    // The content is portaled, so we walk the click target's ancestors looking
    // for the popover content — and any nested quill portal (Select, menus) — to
    // decide whether the click landed inside.
    useEffect(() => {
        if (!visible) {
            return undefined
        }
        const handler = (event: PointerEvent): void => {
            const target = event.target as Element | null
            if (!target) {
                return
            }
            if (
                target.closest?.('[data-slot="popover-content"]') ||
                target.closest?.('[data-quill-portal]') ||
                anchorRef.current?.contains(target)
            ) {
                return
            }
            onClose()
        }
        // Defer one task so we don't catch the same click that just opened us.
        const timer = window.setTimeout(() => document.addEventListener('pointerdown', handler, true), 0)
        return () => {
            window.clearTimeout(timer)
            document.removeEventListener('pointerdown', handler, true)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [visible])

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <div className="flex w-full min-w-0 items-center gap-1">
                <FilterOperatorToggle />
                <div ref={anchorRef} className="min-w-0 flex-1">
                    <Popover
                        open={visible}
                        onOpenChange={(open, details) => {
                            if (open) {
                                setVisible(true)
                                return
                            }
                            // Escape closes; other dismiss reasons are handled by the
                            // pointerdown listener above, so cancel base-ui's own dismiss.
                            if (details?.reason === 'escape-key') {
                                onClose()
                                return
                            }
                            details?.cancel()
                        }}
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
                        <PopoverContent
                            anchor={anchorRef}
                            align="start"
                            initialFocus={false}
                            finalFocus={false}
                            className="w-auto p-0"
                        >
                            <div ref={popupRef} className="w-[400px] md:w-[600px]">
                                <InfiniteSelectResults
                                    focusInput={() => searchInputRef.current?.focus()}
                                    taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                                    popupAnchorElement={popupRef.current}
                                />
                            </div>
                        </PopoverContent>
                    </Popover>
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
