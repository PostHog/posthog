import { useActions, useValues } from 'kea'

import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { FilterBar } from 'lib/components/FilterBar'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'

import { MCPCallerKind } from '~/queries/schema/schema-general'

import { McpDateFilter } from '../components/McpDateFilter'
import { formatNumber } from '../dashboard/formatters'
import { mcpOverviewLogic } from './mcpOverviewLogic'

const CALLER_KIND_OPTIONS: { value: MCPCallerKind; label: string; 'data-attr': string }[] = [
    { value: 'people', label: 'People', 'data-attr': 'mcp-overview-caller-people' },
    { value: 'automations', label: 'Automations', 'data-attr': 'mcp-overview-caller-automations' },
    { value: 'all', label: 'Everything', 'data-attr': 'mcp-overview-caller-all' },
]

function AutomationsHiddenNote(): JSX.Element | null {
    const { callerKind, summary } = useValues(mcpOverviewLogic)
    const { setCallerKind } = useActions(mcpOverviewLogic)

    if (callerKind !== 'people' || !summary || summary.automation_calls === 0) {
        return null
    }
    return (
        <span className="flex flex-wrap items-center gap-1 text-xs text-muted">
            <span>Automations hidden:</span>
            <span translate="no">{formatNumber(summary.automation_calls)}</span>
            <span>calls from</span>
            <span translate="no">{formatNumber(summary.automation_sessions)}</span>
            <span>sessions.</span>
            <LemonButton size="xsmall" onClick={() => setCallerKind('all')} data-attr="mcp-overview-show-automations">
                Show
            </LemonButton>
        </span>
    )
}

export function OverviewFilterBar(): JSX.Element {
    const { dateFilter, callerKind, propertyFilters, filterTestAccounts, reloading } = useValues(mcpOverviewLogic)
    const { setDateFilter, setCallerKind, setPropertyFilters, setFilterTestAccounts } = useActions(mcpOverviewLogic)

    return (
        <FilterBar
            left={
                <>
                    <McpDateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={(dateFrom, dateTo) => setDateFilter(dateFrom, dateTo)}
                        dataAttr="mcp-overview-date-filter"
                    />
                    <LemonSegmentedButton
                        size="small"
                        value={callerKind}
                        onChange={setCallerKind}
                        options={CALLER_KIND_OPTIONS}
                        disabledReason={reloading ? 'Loading the current selection' : undefined}
                    />
                    <div data-attr="mcp-overview-property-filter">
                        <PropertyFilters
                            pageKey="mcp-analytics-overview"
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
                </>
            }
            right={
                <div className="flex flex-wrap items-center justify-end gap-2">
                    <AutomationsHiddenNote />
                    <TestAccountFilterSwitch
                        checked={filterTestAccounts}
                        onChange={setFilterTestAccounts}
                        data-attr="mcp-overview-test-account-filter"
                    />
                </div>
            }
        />
    )
}
