import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconRefresh, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { cn } from 'lib/utils/css-classes'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'
import { McpInternalUsersFilter } from './McpInternalUsersFilter'

const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.MCPProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]

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
                buttonSize="small"
                renderControls={({ addFilter, activeFilters, clearFilters }) => (
                    <div className="flex w-full min-w-0 flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            {children}
                            {addFilter}
                            {activeFilters.length > 0 && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconX />}
                                    aria-label="Clear property filters"
                                    tooltip="Clear property filters"
                                    onClick={clearFilters}
                                    data-attr={`${dataAttrPrefix}-clear-filters`}
                                />
                            )}
                            <McpInternalUsersFilter dataAttr={`${dataAttrPrefix}-test-account-filter`} />
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconRefresh />}
                                aria-label="Refresh"
                                tooltip="Refresh data"
                                onClick={onRefresh}
                                loading={refreshing}
                                data-attr={`${dataAttrPrefix}-refresh`}
                            />
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
