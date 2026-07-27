import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter } from '@posthog/icons'

import { TaxonomicFilterHeadless } from 'lib/components/TaxonomicFilter/headless'
import { TaxonomicFilterMenu } from 'lib/components/TaxonomicFilter/menu/TaxonomicFilterMenu'
import { ExcludedProperties, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Button, ToggleGroup, ToggleGroupItem } from 'lib/ui/quill'

import { FilterLogicalOperator, PropertyFilterType, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

import { TAXONOMIC_FILTER_LOGIC_KEY, TAXONOMIC_GROUP_TYPES } from './consts'
import { issueFiltersLogic } from './issueFiltersLogic'

const ERROR_TRACKING_EVENT_NAMES = ['$exception']
const ERROR_TRACKING_EXCLUDED_PROPERTIES: ExcludedProperties = {
    [TaxonomicFilterGroupType.ErrorTrackingIssues]: ['assignee'],
    [TaxonomicFilterGroupType.EventProperties]: [
        '$exception_type',
        '$exception_value',
        '$exception_message',
        '$exception_source',
        '$exception_function',
    ],
}

export const FilterGroup = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    excludeFilterTypes,
    activeFiltersInline = false,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    excludeFilterTypes?: PropertyFilterType[]
    activeFiltersInline?: boolean
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
            <FilterControls taxonomicGroupTypes={taxonomicGroupTypes} activeFiltersInline={activeFiltersInline} />
        </UniversalFilters>
    )
}

const FilterControls = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    nested = false,
    activeFiltersInline = false,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    nested?: boolean
    activeFiltersInline?: boolean
}): JSX.Element => {
    const filterRow = (
        <div className="relative flex shrink-0 items-center gap-1">
            {nested ? <FilterOperatorToggle /> : null}
            <FilterPicker taxonomicGroupTypes={taxonomicGroupTypes} />
            {nested ? null : <FilterOperatorToggle />}
        </div>
    )

    if (nested) {
        return (
            <div className="flex w-full min-w-0 flex-col gap-1">
                {filterRow}
                <UniversalFilterGroup taxonomicGroupTypes={taxonomicGroupTypes} className="flex flex-wrap gap-1" />
            </div>
        )
    }

    return (
        <>
            {filterRow}
            <UniversalFilterGroup
                taxonomicGroupTypes={taxonomicGroupTypes}
                className={
                    activeFiltersInline
                        ? 'flex flex-1 flex-wrap items-center gap-1'
                        : 'order-last flex w-full flex-wrap items-center gap-1'
                }
                dataAttr="error-tracking-active-filters"
            />
        </>
    )
}

const FilterPicker = ({ taxonomicGroupTypes }: { taxonomicGroupTypes: TaxonomicFilterGroupType[] }): JSX.Element => {
    const { addGroupFilter } = useActions(universalFiltersLogic)

    return (
        <TaxonomicFilterHeadless.Root
            className="contents"
            bindRootProps={false}
            groupType={taxonomicGroupTypes[0] ?? TaxonomicFilterGroupType.ErrorTrackingProperties}
            taxonomicGroupTypes={taxonomicGroupTypes}
            eventNames={ERROR_TRACKING_EVENT_NAMES}
            excludedProperties={ERROR_TRACKING_EXCLUDED_PROPERTIES}
            onChange={(group, value, item) => addGroupFilter(group, value, item)}
        >
            <TaxonomicFilterMenu
                trigger={({ open }) => (
                    <Button variant="outline" size="default" aria-expanded={open}>
                        <IconFilter />
                        Add filter
                    </Button>
                )}
            />
        </TaxonomicFilterHeadless.Root>
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
        <ToggleGroup
            variant="outline"
            size="default"
            className="shrink-0"
            value={[filterGroup.type]}
            onValueChange={([type]) => {
                if (type === FilterLogicalOperator.And || type === FilterLogicalOperator.Or) {
                    setGroupType(type)
                }
            }}
        >
            {FILTER_LOGICAL_OPERATOR_OPTIONS.map((option) => (
                <ToggleGroupItem key={option.value} value={option.value} title={option.tooltip}>
                    {option.label}
                </ToggleGroupItem>
            ))}
        </ToggleGroup>
    )
}

const UniversalFilterGroup = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    className,
    dataAttr,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    className?: string
    dataAttr?: string
}): JSX.Element | null => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    if (filterGroup.values.length === 0) {
        return null
    }

    const values = filterGroup.values.map((filterOrGroup: UniversalFiltersGroupValue, index: number) => {
        return isUniversalGroupFilterLike(filterOrGroup) ? (
            <UniversalFilters.Group index={index} key={index} group={filterOrGroup}>
                <FilterControls taxonomicGroupTypes={taxonomicGroupTypes} nested />
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
    })

    return className ? (
        <div className={className} data-attr={dataAttr}>
            {values}
        </div>
    ) : (
        <>{values}</>
    )
}
