import { useActions, useValues } from 'kea'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { IconFilter } from '@posthog/icons'

import { TaxonomicFilterHeadless } from 'lib/components/TaxonomicFilter/headless'
import { TaxonomicFilterMenu } from 'lib/components/TaxonomicFilter/menu/TaxonomicFilterMenu'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { Button, ToggleGroup, ToggleGroupItem } from 'lib/ui/quill'

import { FilterLogicalOperator, PropertyFilterType, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

import { TAXONOMIC_FILTER_LOGIC_KEY, TAXONOMIC_GROUP_TYPES } from './consts'
import { issueFiltersLogic } from './issueFiltersLogic'

const ERROR_TRACKING_EVENT_NAMES = ['$exception']

export const FilterGroup = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    excludeFilterTypes,
    activeFiltersInline = false,
    iconOnly = false,
    renderControls,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    excludeFilterTypes?: PropertyFilterType[]
    activeFiltersInline?: boolean
    iconOnly?: boolean
    renderControls?: (controls: { filterPicker: ReactNode; activeFilters: ReactNode }) => ReactNode
} = {}): JSX.Element => {
    const { filterAddedFromPreview, filterGroup } = useValues(issueFiltersLogic)
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
            <FilterControls
                taxonomicGroupTypes={taxonomicGroupTypes}
                activeFiltersInline={activeFiltersInline}
                iconOnly={iconOnly}
                filterAddedFromPreview={filterAddedFromPreview}
                renderControls={renderControls}
            />
        </UniversalFilters>
    )
}

const FilterControls = ({
    taxonomicGroupTypes = TAXONOMIC_GROUP_TYPES,
    nested = false,
    activeFiltersInline = false,
    iconOnly = false,
    filterAddedFromPreview = 0,
    renderControls,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    nested?: boolean
    activeFiltersInline?: boolean
    iconOnly?: boolean
    filterAddedFromPreview?: number
    renderControls?: (controls: { filterPicker: ReactNode; activeFilters: ReactNode }) => ReactNode
}): JSX.Element => {
    const filterRow = (
        <div className={`relative flex shrink-0 items-center ${activeFiltersInline ? 'gap-2' : 'gap-1'}`}>
            {nested ? <FilterOperatorToggle /> : null}
            <FilterPicker taxonomicGroupTypes={taxonomicGroupTypes} iconOnly={iconOnly} />
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

    if (renderControls) {
        return (
            <>
                {renderControls({
                    filterPicker: (
                        <div className="relative flex shrink-0 items-center">
                            <FilterPicker taxonomicGroupTypes={taxonomicGroupTypes} iconOnly={iconOnly} />
                        </div>
                    ),
                    activeFilters: (
                        <UniversalFilterGroup
                            taxonomicGroupTypes={taxonomicGroupTypes}
                            filterAddedFromPreview={filterAddedFromPreview}
                            prefix={<FilterOperatorToggle />}
                            className="flex w-full flex-wrap items-center gap-1"
                            dataAttr="error-tracking-active-filters"
                        />
                    ),
                })}
            </>
        )
    }

    if (activeFiltersInline && iconOnly) {
        return (
            <>
                <UniversalFilterGroup
                    taxonomicGroupTypes={taxonomicGroupTypes}
                    filterAddedFromPreview={filterAddedFromPreview}
                    className="flex min-w-0 flex-nowrap items-center gap-1 overflow-hidden"
                    dataAttr="error-tracking-active-filters"
                />
                {filterRow}
            </>
        )
    }

    return (
        <>
            {filterRow}
            <UniversalFilterGroup
                taxonomicGroupTypes={taxonomicGroupTypes}
                filterAddedFromPreview={filterAddedFromPreview}
                className={
                    activeFiltersInline
                        ? 'flex flex-1 flex-wrap items-center gap-2'
                        : 'order-last flex w-full flex-wrap items-center gap-1'
                }
                dataAttr="error-tracking-active-filters"
            />
        </>
    )
}

const FilterPicker = ({
    taxonomicGroupTypes,
    iconOnly,
}: {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    iconOnly: boolean
}): JSX.Element => {
    const { addGroupFilter } = useActions(universalFiltersLogic)
    const [openRequest, setOpenRequest] = useState(0)

    return (
        <TaxonomicFilterHeadless.Root
            className="contents"
            bindRootProps={false}
            groupType={taxonomicGroupTypes[0] ?? TaxonomicFilterGroupType.ErrorTrackingProperties}
            taxonomicGroupTypes={taxonomicGroupTypes}
            eventNames={ERROR_TRACKING_EVENT_NAMES}
            onChange={(group, value, item) => addGroupFilter(group, value, item)}
        >
            <TaxonomicFilterMenu
                key={openRequest}
                defaultOpen={openRequest > 0}
                defaultOpenState="combobox"
                trigger={({ open }) => (
                    <Button
                        variant={iconOnly ? 'default' : 'outline'}
                        size={iconOnly ? 'icon-sm' : 'default'}
                        aria-label={iconOnly ? 'Add filter' : undefined}
                        title={iconOnly ? 'Add filter' : undefined}
                        aria-expanded={open}
                        onClick={() => {
                            if (!open) {
                                setOpenRequest((request) => request + 1)
                            }
                        }}
                    >
                        <IconFilter />
                        {!iconOnly && 'Add filter'}
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
            size="sm"
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
    prefix,
    filterAddedFromPreview = 0,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    className?: string
    dataAttr?: string
    prefix?: ReactNode
    filterAddedFromPreview?: number
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
                initiallyOpen={
                    allowInitiallyOpen &&
                    filterOrGroup.type != PropertyFilterType.HogQL &&
                    index < filterGroup.values.length - filterAddedFromPreview
                }
            />
        )
    })

    return className ? (
        <div className={className} data-attr={dataAttr}>
            {prefix}
            {values}
        </div>
    ) : (
        <>
            {prefix}
            {values}
        </>
    )
}
