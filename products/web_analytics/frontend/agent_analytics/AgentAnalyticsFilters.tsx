import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { webAnalyticsDateMapping } from 'scenes/web-analytics/constants'
import { WebAnalyticsDomainSelector } from 'scenes/web-analytics/WebAnalyticsFilters'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { WebConversionGoal } from 'scenes/web-analytics/WebConversionGoal'
import { WebPropertyFilters } from 'scenes/web-analytics/WebPropertyFilters'

import { AgentScope, agentAnalyticsLogic } from './agentAnalyticsLogic'

const SCOPE_OPTIONS: { value: AgentScope; label: string }[] = [
    { value: 'live', label: 'Agents' },
    { value: 'all', label: 'Agents and crawlers' },
]

export const AgentAnalyticsFilters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        compareFilter,
        conversionGoal,
    } = useValues(webAnalyticsLogic)
    const { setDates, setCompareFilter, setConversionGoal } = useActions(webAnalyticsLogic)
    const { scope, anyLoading } = useValues(agentAnalyticsLogic)
    const { setScope, refresh } = useActions(agentAnalyticsLogic)

    return (
        <FilterBar
            top={tabs}
            left={
                <>
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={refresh}
                        icon={anyLoading ? <Spinner textColored /> : <IconRefresh />}
                        disabledReason={anyLoading ? 'Loading' : undefined}
                        aria-label="Reload agent analytics"
                        data-attr="agent-analytics-reload"
                    />
                    <DateFilter
                        dateOptions={webAnalyticsDateMapping}
                        allowTimePrecision
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                    />
                    <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                    <WebConversionGoal value={conversionGoal} onChange={setConversionGoal} />
                </>
            }
            right={
                <>
                    <WebAnalyticsDomainSelector />
                    <WebPropertyFilters />
                    <LemonSegmentedButton size="small" value={scope} onChange={setScope} options={SCOPE_OPTIONS} />
                </>
            }
        />
    )
}
