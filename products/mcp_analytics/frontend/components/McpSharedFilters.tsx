import { useActions, useValues } from 'kea'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'

export interface McpSharedFiltersProps {
    /** Distinct PropertyFilters storage key per page, so per-tab filter picker state doesn't collide. */
    pageKey: string
    dataAttrPrefix: string
}

// The property filters and "Filter out internal and test users" switch shared by every MCP
// analytics tab, all reading and writing mcpAnalyticsFiltersLogic so a change made on one tab
// carries to the others through the URL.
export function McpSharedFilters({ pageKey, dataAttrPrefix }: McpSharedFiltersProps): JSX.Element {
    const { filterTestAccounts, propertyFilters } = useValues(mcpAnalyticsFiltersLogic)
    const { setFilterTestAccounts, setPropertyFilters } = useActions(mcpAnalyticsFiltersLogic)

    return (
        <>
            <div data-attr={`${dataAttrPrefix}-property-filter`}>
                <PropertyFilters
                    pageKey={pageKey}
                    propertyFilters={propertyFilters}
                    onChange={setPropertyFilters}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.MCPProperties,
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.EventFeatureFlags,
                    ]}
                    eventNames={['$mcp_tool_call']}
                    buttonText="Add filter"
                />
            </div>
            <TestAccountFilterSwitch
                checked={filterTestAccounts}
                onChange={setFilterTestAccounts}
                data-attr={`${dataAttrPrefix}-test-account-filter`}
            />
        </>
    )
}
