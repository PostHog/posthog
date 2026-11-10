import './PropertyGroupFilters.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useMemo } from 'react'

import { IconCopy, IconPlus, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { Button, Separator } from '@posthog/quill'

import { AddBehavioralFilterButton } from 'lib/components/PropertyFilters/components/AddBehavioralFilterButton'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { inlineEquivalentPropertyGroups, isPropertyGroupFilterLike } from 'lib/components/PropertyFilters/utils'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { keyForInsightLogicProps } from 'lib/insights/sharedUtils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { InsightQueryNode, ProductAnalyticsInsightQueryNode } from '~/queries/schema/schema-general'
import { InsightLogicProps, PropertyGroupFilterValue } from '~/types'

import { InsightTestAccountFilter } from '../filters/InsightTestAccountFilter'
import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'

type PropertyGroupFiltersProps = {
    insightProps: InsightLogicProps
    query: ProductAnalyticsInsightQueryNode
    setQuery: (node: ProductAnalyticsInsightQueryNode) => void
    pageKey: string
    eventNames?: string[]
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    globalFiltersUnsupported?: boolean
}

export function PropertyGroupFilters({
    insightProps,
    query,
    setQuery,
    pageKey,
    eventNames = [],
    taxonomicGroupTypes,
    globalFiltersUnsupported,
}: PropertyGroupFiltersProps): JSX.Element {
    const logicProps = { query, setQuery, pageKey }
    const { featureFlags } = useValues(featureFlagLogic)
    const { propertyGroupFilter } = useValues(propertyGroupFilterLogic(logicProps))
    const {
        addFilterGroup,
        removeFilterGroup,
        duplicateFilterGroup,
        setOuterPropertyGroupsType,
        setInnerPropertyGroupType,
        setPropertyFilters,
    } = useActions(propertyGroupFilterLogic(logicProps))
    const quillSurface = useQuillSurface()

    const behavioralFiltersEnabled = !!featureFlags[FEATURE_FLAGS.BEHAVIORAL_PROPERTY_FILTER]
    const groupRows = useMemo(
        () =>
            propertyGroupFilter.values?.map((group: PropertyGroupFilterValue) =>
                isPropertyGroupFilterLike(group) ? inlineEquivalentPropertyGroups(group.values, group.type) : null
            ) ?? [],
        [propertyGroupFilter.values]
    )
    const showHeader = propertyGroupFilter.type && propertyGroupFilter.values.length > 1
    const disabledReason = globalFiltersUnsupported
        ? 'Filter groups cannot be added to insights with a data warehouse series. Please use individual series filters instead.'
        : undefined
    return (
        <div className="deprecated-space-y-2 PropertyGroupFilters @container">
            {propertyGroupFilter.values && (
                <BindLogic logic={propertyGroupFilterLogic} props={logicProps}>
                    <div className="flex flex-col gap-2 @lg:flex-row @lg:items-center">
                        <div className="order-2 @lg:order-none PropertyGroupFilters__add-filter-group-inline-wrapper">
                            {quillSurface ? (
                                <div className="PropertyGroupFilters__add-filter-group-inline">
                                    <Button
                                        data-attr={`${pageKey}-add-filter-group-inline`}
                                        variant="outline"
                                        onClick={addFilterGroup}
                                        disabledReason={disabledReason}
                                    >
                                        <IconPlus />
                                        Add filter group
                                    </Button>
                                </div>
                            ) : (
                                <LemonButton
                                    data-attr={`${pageKey}-add-filter-group-inline`}
                                    type="secondary"
                                    onClick={addFilterGroup}
                                    icon={<IconPlusSmall />}
                                    sideIcon={null}
                                    disabledReason={disabledReason}
                                    className="PropertyGroupFilters__add-filter-group-inline"
                                >
                                    Add filter group
                                </LemonButton>
                            )}
                        </div>
                        <div className="order-1 @lg:order-none">
                            <InsightTestAccountFilter
                                disabledReason={disabledReason}
                                query={query}
                                setQuery={setQuery as (node: InsightQueryNode) => void}
                            />
                        </div>
                    </div>

                    {showHeader ? (
                        <>
                            <div className="flex items-center justify-between">
                                {propertyGroupFilter.type && propertyGroupFilter.values.length > 1 && (
                                    <AndOrFilterSelect
                                        value={propertyGroupFilter.type}
                                        onChange={(value) => setOuterPropertyGroupsType(value)}
                                        topLevelFilter={true}
                                        suffix={['group', 'groups']}
                                    />
                                )}
                            </div>
                            {quillSurface ? <Separator className="my-4" /> : <LemonDivider className="my-4" />}
                        </>
                    ) : null}
                    {propertyGroupFilter.values?.length ? (
                        <div>
                            {propertyGroupFilter.values?.map(
                                (group: PropertyGroupFilterValue, propertyGroupIndex: number) => {
                                    return (
                                        <React.Fragment key={propertyGroupIndex}>
                                            <div
                                                className={
                                                    behavioralFiltersEnabled
                                                        ? 'property-group--framed flex min-w-0 flex-col overflow-hidden rounded border'
                                                        : 'property-group'
                                                }
                                            >
                                                <div
                                                    className={clsx(
                                                        'flex items-center',
                                                        behavioralFiltersEnabled
                                                            ? 'gap-x-2 border-b px-2.5 py-2'
                                                            : 'justify-between mb-2'
                                                    )}
                                                >
                                                    <AndOrFilterSelect
                                                        onChange={(type) =>
                                                            setInnerPropertyGroupType(type, propertyGroupIndex)
                                                        }
                                                        value={group.type}
                                                        shortSuffix={behavioralFiltersEnabled ? 'in group' : undefined}
                                                    />
                                                    {!behavioralFiltersEnabled &&
                                                        (quillSurface ? (
                                                            <Separator className="mx-2 w-auto flex-1 @max-sm/editor-panel:hidden" />
                                                        ) : (
                                                            <LemonDivider className="flex-1 mx-2 @max-[410px]/editor-panel:hidden" />
                                                        ))}
                                                    <div
                                                        className={clsx(
                                                            'flex shrink-0 items-center gap-1',
                                                            behavioralFiltersEnabled && 'ml-auto'
                                                        )}
                                                    >
                                                        {quillSurface ? (
                                                            <>
                                                                <Button
                                                                    size="icon"
                                                                    aria-label="Duplicate filter group"
                                                                    tooltip="Duplicate filter group"
                                                                    onClick={() =>
                                                                        duplicateFilterGroup(propertyGroupIndex)
                                                                    }
                                                                >
                                                                    <IconCopy />
                                                                </Button>
                                                                <Button
                                                                    size="icon"
                                                                    aria-label="Delete filter group"
                                                                    tooltip="Delete filter group"
                                                                    onClick={() =>
                                                                        removeFilterGroup(propertyGroupIndex)
                                                                    }
                                                                >
                                                                    <IconTrash />
                                                                </Button>
                                                            </>
                                                        ) : (
                                                            <>
                                                                <LemonButton
                                                                    icon={<IconCopy />}
                                                                    onClick={() =>
                                                                        duplicateFilterGroup(propertyGroupIndex)
                                                                    }
                                                                    size="small"
                                                                />
                                                                <LemonButton
                                                                    icon={<IconTrash />}
                                                                    onClick={() =>
                                                                        removeFilterGroup(propertyGroupIndex)
                                                                    }
                                                                    size="small"
                                                                />
                                                            </>
                                                        )}
                                                    </div>
                                                </div>
                                                <div
                                                    className={
                                                        behavioralFiltersEnabled
                                                            ? 'bg-primary px-2.5 py-2.5'
                                                            : undefined
                                                    }
                                                >
                                                    <PropertyFilters
                                                        addText="Filter"
                                                        propertyFilters={groupRows[propertyGroupIndex]}
                                                        onChange={(properties) => {
                                                            setPropertyFilters(properties, propertyGroupIndex)
                                                        }}
                                                        pageKey={`${keyForInsightLogicProps('new')(
                                                            insightProps
                                                        )}-PropertyGroupFilters-${propertyGroupIndex}`}
                                                        taxonomicGroupTypes={taxonomicGroupTypes}
                                                        eventNames={eventNames}
                                                        propertyGroupType={group.type}
                                                        orFiltering
                                                        logicalRowDivider={behavioralFiltersEnabled}
                                                        hasRowOperator={!behavioralFiltersEnabled}
                                                        addFilterDivider={behavioralFiltersEnabled}
                                                        addFilterSuffix={
                                                            behavioralFiltersEnabled
                                                                ? (addFilter) => (
                                                                      <AddBehavioralFilterButton
                                                                          data-attr={`${pageKey}-add-behavioral-filter`}
                                                                          onAdd={addFilter}
                                                                      />
                                                                  )
                                                                : null
                                                        }
                                                    />
                                                </div>
                                            </div>
                                            {propertyGroupIndex !== propertyGroupFilter.values.length - 1 && (
                                                <div className="property-group-and-or-separator">
                                                    <span>{propertyGroupFilter.type}</span>
                                                </div>
                                            )}
                                        </React.Fragment>
                                    )
                                }
                            )}
                        </div>
                    ) : null}

                    {quillSurface ? (
                        <div className="PropertyGroupFilters__add-filter-group-after">
                            <Button
                                data-attr={`${pageKey}-add-filter-group`}
                                variant="outline"
                                onClick={addFilterGroup}
                                disabledReason={disabledReason}
                            >
                                <IconPlus />
                                Add filter group
                            </Button>
                        </div>
                    ) : (
                        <LemonButton
                            data-attr={`${pageKey}-add-filter-group`}
                            type="secondary"
                            onClick={addFilterGroup}
                            icon={<IconPlusSmall />}
                            sideIcon={null}
                            disabledReason={disabledReason}
                            className="PropertyGroupFilters__add-filter-group-after"
                        >
                            Add filter group
                        </LemonButton>
                    )}
                </BindLogic>
            )}
        </div>
    )
}
