import { useActions, useValues } from 'kea'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { MCP_TOOL_CALL_EVENT } from 'lib/components/TaxonomicFilter/utils/mcpProperties'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { cn } from 'lib/utils/css-classes'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'

const TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.MCPProperties,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]

interface McpSharedFiltersProps {
    /** Namespaces the property filter's popover state. Unique per tab. */
    pageKey: string
    /** Prefix for the two `data-attr` values, e.g. "mcp-dashboard" -> "mcp-dashboard-property-filter". */
    dataAttrPrefix: string
    className?: string
}

/** The property filters and internal-user switch every MCP analytics tab shares, wired to mcpAnalyticsFiltersLogic. */
export function McpSharedFilters({ pageKey, dataAttrPrefix, className }: McpSharedFiltersProps): JSX.Element {
    const { filterTestAccounts, propertyFilters } = useValues(mcpAnalyticsFiltersLogic)
    const { setFilterTestAccounts, setPropertyFilters } = useActions(mcpAnalyticsFiltersLogic)

    return (
        <div className={cn('flex flex-row flex-wrap items-center gap-2', className)}>
            <div data-attr={`${dataAttrPrefix}-property-filter`}>
                <PropertyFilters
                    pageKey={pageKey}
                    propertyFilters={propertyFilters}
                    onChange={setPropertyFilters}
                    taxonomicGroupTypes={TAXONOMIC_GROUP_TYPES}
                    eventNames={[MCP_TOOL_CALL_EVENT]}
                    buttonText="Add filter"
                />
            </div>
            <TestAccountFilterSwitch
                checked={filterTestAccounts}
                onChange={setFilterTestAccounts}
                data-attr={`${dataAttrPrefix}-test-account-filter`}
            />
        </div>
    )
}
