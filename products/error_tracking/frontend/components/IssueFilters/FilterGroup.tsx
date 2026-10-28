import { useActions, useValues } from 'kea'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { IconFilter } from '@posthog/icons'
import { Popover } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    ToggleGroup,
    ToggleGroupItem,
} from 'lib/ui/quill'

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
    menuItems,
    leadingFilters,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    excludeFilterTypes?: PropertyFilterType[]
    activeFiltersInline?: boolean
    iconOnly?: boolean
    renderControls?: (controls: { filterPicker: ReactNode; activeFilters: ReactNode }) => ReactNode
    // Extra rows for the filter button's menu. With them, the button opens that menu, not the search.
    menuItems?: ReactNode
    leadingFilters?: ReactNode
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
                menuItems={menuItems}
                leadingFilters={leadingFilters}
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
    menuItems,
    leadingFilters,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    nested?: boolean
    activeFiltersInline?: boolean
    iconOnly?: boolean
    filterAddedFromPreview?: number
    renderControls?: (controls: { filterPicker: ReactNode; activeFilters: ReactNode }) => ReactNode
    menuItems?: ReactNode
    leadingFilters?: ReactNode
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
                            <FilterPicker
                                taxonomicGroupTypes={taxonomicGroupTypes}
                                iconOnly={iconOnly}
                                menuItems={menuItems}
                            />
                        </div>
                    ),
                    activeFilters: (
                        <UniversalFilterGroup
                            taxonomicGroupTypes={taxonomicGroupTypes}
                            filterAddedFromPreview={filterAddedFromPreview}
                            leadingFilters={leadingFilters}
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
    menuItems,
}: {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    iconOnly: boolean
    menuItems?: ReactNode
}): JSX.Element => {
    const { addGroupFilter } = useActions(universalFiltersLogic)
    const [pickerOpen, setPickerOpen] = useState(false)
    const [pickerAnchor, setPickerAnchor] = useState<HTMLSpanElement | null>(null)

    const buttonProps = {
        variant: iconOnly ? 'default' : 'outline',
        size: iconOnly ? 'icon-sm' : 'default',
        'aria-label': iconOnly ? 'Add filter' : undefined,
        title: iconOnly ? 'Add filter' : undefined,
        children: (
            <>
                <IconFilter />
                {!iconOnly && 'Add filter'}
            </>
        ),
    } as const

    return (
        <>
            <span ref={setPickerAnchor} className="inline-flex">
                {menuItems ? (
                    <DropdownMenu>
                        <DropdownMenuTrigger render={<Button {...buttonProps} />} />
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => setPickerOpen(true)}>Add filter</DropdownMenuItem>
                            <DropdownMenuSeparator />
                            {menuItems}
                        </DropdownMenuContent>
                    </DropdownMenu>
                ) : (
                    <Button {...buttonProps} aria-expanded={pickerOpen} onClick={() => setPickerOpen(!pickerOpen)} />
                )}
            </span>
            {/* Beside the trigger, not around it: a LemonDropdown around a quill menu stops the menu opening. */}
            <Popover
                referenceElement={pickerAnchor}
                visible={pickerOpen}
                onClickOutside={() => setPickerOpen(false)}
                overlay={
                    <TaxonomicFilter
                        groupType={taxonomicGroupTypes[0] ?? TaxonomicFilterGroupType.ErrorTrackingProperties}
                        taxonomicGroupTypes={taxonomicGroupTypes}
                        eventNames={ERROR_TRACKING_EVENT_NAMES}
                        onChange={(group, value, item) => {
                            addGroupFilter(group, value, item)
                            setPickerOpen(false)
                        }}
                        enableKeywordShortcuts
                    />
                }
            />
        </>
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
    leadingFilters,
    filterAddedFromPreview = 0,
}: {
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    className?: string
    dataAttr?: string
    prefix?: ReactNode
    leadingFilters?: ReactNode
    filterAddedFromPreview?: number
}): JSX.Element | null => {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)
    const [allowInitiallyOpen, setAllowInitiallyOpen] = useState<boolean>(false)

    useOnMountEffect(() => setAllowInitiallyOpen(true))

    if (filterGroup.values.length === 0 && !leadingFilters) {
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
            {leadingFilters}
            {prefix}
            {values}
        </div>
    ) : (
        <>
            {leadingFilters}
            {prefix}
            {values}
        </>
    )
}
