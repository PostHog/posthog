import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconRefresh, IconX } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { cn } from 'lib/utils/css-classes'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { McpInternalUsersFilter } from './McpInternalUsersFilter'

const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.MCPProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]

// PropertyFilters always renders its add button as a raised LemonButton. These overrides remove the
// 3D ledge and match the height and text size of the quill outline buttons in the same row.
const FLAT_ADD_FILTER_BUTTON =
    '[--lemon-button-chrome-depth:0px]! [--lemon-button-hover-depth:0px]! [--lemon-button-press-depth:0px]! [--lemon-button-frame-bg-color:transparent]! [--lemon-button-height:1.5rem]! [--lemon-button-font-size:0.75rem]! [--lemon-button-icon-size:0.875rem]! [--lemon-button-padding-vertical:0.125rem]!'

interface McpSharedFiltersProps {
    pageKey: string
    dataAttrPrefix: string
    className?: string
    children?: ReactNode
    onRefresh: () => void
    refreshing: boolean
}

export function McpSharedFilters({
    pageKey,
    dataAttrPrefix,
    className,
    children,
    onRefresh,
    refreshing,
}: McpSharedFiltersProps): JSX.Element {
    const { propertyFilters } = useValues(mcpAnalyticsFiltersLogic)
    const { setPropertyFilters } = useActions(mcpAnalyticsFiltersLogic)

    return (
        <div className={cn('w-full min-w-0', className)} data-attr={`${dataAttrPrefix}-property-filter`}>
            <PropertyFilters
                pageKey={pageKey}
                propertyFilters={propertyFilters}
                onChange={setPropertyFilters}
                taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
                eventNames={[MCP_TOOL_CALL_EVENT]}
                buttonText="Add filter"
                buttonClassName={FLAT_ADD_FILTER_BUTTON}
                buttonSize="small"
                renderControls={({ addFilter, activeFilters, clearFilters }) => (
                    <div className="flex w-full min-w-0 flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            {children}
                            {addFilter}
                            {activeFilters.length > 0 && (
                                <Button
                                    variant="outline"
                                    size="icon-sm"
                                    aria-label="Clear property filters"
                                    tooltip="Clear property filters"
                                    onClick={clearFilters}
                                    data-attr={`${dataAttrPrefix}-clear-filters`}
                                >
                                    <IconX />
                                </Button>
                            )}
                            <McpInternalUsersFilter dataAttr={`${dataAttrPrefix}-test-account-filter`} />
                            <Button
                                variant="outline"
                                size="icon-sm"
                                aria-label="Refresh"
                                tooltip="Refresh data"
                                onClick={onRefresh}
                                loading={refreshing}
                                data-attr={`${dataAttrPrefix}-refresh`}
                            >
                                <IconRefresh />
                            </Button>
                        </div>
                        {activeFilters.length > 0 && (
                            <div className="flex min-w-0 flex-wrap items-center gap-2">{activeFilters}</div>
                        )}
                    </div>
                )}
            />
        </div>
    )
}
