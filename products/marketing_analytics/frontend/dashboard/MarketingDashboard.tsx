import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCard, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { urls } from 'scenes/urls'
import { AttributionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab'
import { RetentionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/RetentionTab/RetentionTab'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'

import { DashboardSection, TRAFFIC_BREAKDOWNS, trafficQuery } from './dashboardQueries'
import { marketingDashboardLogic } from './marketingDashboardLogic'
import { MarketingRevenue } from './MarketingRevenue'
import { TrafficTable } from './TrafficTable'

const SECTIONS: { key: DashboardSection; label: string; description: string }[] = [
    { key: 'acquisition', label: 'Acquisition', description: 'Visitors, sessions and pageviews' },
    { key: 'engagement', label: 'Engagement', description: 'Session duration and bounce rate' },
    { key: 'retention', label: 'Retention', description: 'Returning visitors by cohort' },
    { key: 'conversion', label: 'Conversion', description: 'Goals and conversion paths' },
    { key: 'revenue', label: 'Revenue', description: 'Revenue by attribution model' },
]

export function MarketingDashboard(): JSX.Element {
    const { updateFilterTestAccounts } = useActions(marketingAnalyticsSettingsLogic)
    const { section, breakdown } = useValues(marketingDashboardLogic)
    const { setSection, setBreakdown } = useActions(marketingDashboardLogic)
    const { dateFilter, compareFilter, shouldFilterTestAccounts, hasSources, loading } =
        useValues(marketingAnalyticsLogic)
    const { setDates, setCompareFilter, setActiveTab, setSetupSection } = useActions(marketingAnalyticsLogic)
    const dateRange = { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo }
    const isTraffic = section === 'acquisition' || section === 'engagement'

    return (
        <BindLogic logic={marketingDashboardLogic} props={{}}>
            <div className="flex flex-col gap-5 mt-4" data-attr="marketing-dashboard-v2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-3">
                        <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                        {isTraffic && (
                            <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                        )}
                    </div>
                    <LemonSwitch
                        checked={shouldFilterTestAccounts}
                        onChange={updateFilterTestAccounts}
                        label="Exclude test accounts"
                    />
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            setSetupSection(SetupSection.SUGGESTIONS)
                            setActiveTab(MarketingAnalyticsTab.SETUP)
                        }}
                    >
                        Improve setup
                    </LemonButton>
                </div>
                {!loading && !hasSources && (
                    <LemonBanner
                        type="info"
                        action={{
                            children: 'Connect ad platforms',
                            to: urls.settings('environment-marketing-analytics', 'marketing-settings'),
                        }}
                    >
                        Your website traffic is available without an ad integration. Connect ad platforms to add spend,
                        cost per conversion and ROAS.
                    </LemonBanner>
                )}
                <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
                    {SECTIONS.map((item) => (
                        <LemonButton
                            key={item.key}
                            fullWidth
                            type={section === item.key ? 'primary' : 'secondary'}
                            onClick={() => setSection(item.key)}
                            aria-pressed={section === item.key}
                            data-attr={`marketing-section-${item.key}`}
                        >
                            <div className="py-3 text-left whitespace-normal">
                                <div className="font-semibold text-base">{item.label}</div>
                                <div className="text-xs mt-2 font-normal">{item.description}</div>
                            </div>
                        </LemonButton>
                    ))}
                </div>
                {isTraffic ? (
                    <>
                        <Query
                            query={{
                                kind: NodeKind.WebOverviewQuery,
                                dateRange,
                                compareFilter,
                                filterTestAccounts: shouldFilterTestAccounts,
                                properties: [],
                            }}
                            readOnly
                        />
                        <LemonCard hoverEffect={false}>
                            <h2>{section === 'acquisition' ? 'Visitors over time' : 'Session duration over time'}</h2>
                            <Query
                                key={section}
                                query={trafficQuery(
                                    section,
                                    breakdown,
                                    dateRange,
                                    compareFilter,
                                    shouldFilterTestAccounts,
                                    true
                                )}
                                readOnly
                            />
                        </LemonCard>
                        <LemonCard hoverEffect={false}>
                            <div className="flex flex-wrap justify-between items-center gap-3 mb-4">
                                <h2 className="mb-0">
                                    {section === 'acquisition' ? 'Acquisition' : 'Engagement'} by{' '}
                                    {TRAFFIC_BREAKDOWNS[breakdown].toLowerCase()}
                                </h2>
                                <LemonSelect
                                    value={breakdown}
                                    onChange={(value) => value && setBreakdown(value)}
                                    options={Object.entries(TRAFFIC_BREAKDOWNS).map(([value, label]) => ({
                                        value: value as keyof typeof TRAFFIC_BREAKDOWNS,
                                        label,
                                    }))}
                                />
                            </div>
                            <p className="text-secondary text-sm">
                                Grouped by the session's entry properties. UTM source and referring domain are separate
                                breakdowns.{' '}
                                {section === 'engagement'
                                    ? 'Duration is measured per session. A bounce is a session with one pageview, no autocapture events and a duration under 10 seconds.'
                                    : 'A visitor can appear in more than one row, so row counts may not add up to the total.'}
                            </p>
                            <TrafficTable
                                key={`${section}-${breakdown}`}
                                query={
                                    trafficQuery(section, breakdown, dateRange, compareFilter, shouldFilterTestAccounts)
                                        .source
                                }
                                engagement={section === 'engagement'}
                                breakdownLabel={TRAFFIC_BREAKDOWNS[breakdown]}
                            />
                        </LemonCard>
                        <LemonBanner type="info" action={{ children: 'Open web analytics', to: urls.webAnalytics() }}>
                            {section === 'engagement'
                                ? 'Explore time on page, scroll depth and individual page reports in Web analytics.'
                                : 'Explore landing pages, devices and locations in Web analytics.'}
                        </LemonBanner>
                    </>
                ) : section === 'retention' ? (
                    <RetentionTab />
                ) : section === 'conversion' ? (
                    <AttributionTab />
                ) : (
                    <MarketingRevenue />
                )}
            </div>
        </BindLogic>
    )
}
