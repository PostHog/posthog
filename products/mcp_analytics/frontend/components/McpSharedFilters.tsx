import { useActions, useValues } from 'kea'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'

import { mcpAnalyticsFiltersLogic } from '../mcpAnalyticsFiltersLogic'

export interface McpSharedFiltersProps {
    pageKey: string
    dataAttrPrefix: string
}

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
