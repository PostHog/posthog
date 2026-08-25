import { useActions, useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonInputSelect,
    LemonLabel,
    LemonSegmentedButton,
    LemonTable,
    type LemonTableColumns,
    Link,
    Spinner,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { IntervalFilterStandalone } from 'lib/components/IntervalFilter'
import { dateMapping } from 'lib/utils/dateFilters'
import { BillingLineGraph } from 'scenes/billing/BillingLineGraph'

import {
    type FeatureFlagRequestTypeFilter,
    type FeatureFlagRequestUsageInterval,
    type FeatureFlagRequestUsageMetric,
    type FeatureFlagRequestUsageSdkTotal,
    featureFlagRequestUsageLogic,
} from './featureFlagRequestUsageLogic'
import { RequestUsageSummaryCard } from './RequestUsageSummaryCard'

const DATE_OPTION_KEYS = new Set(['Today', 'Yesterday', 'Last 24 hours', 'Last 7 days', 'Last 14 days', 'Last 30 days'])
const DATE_OPTIONS = dateMapping.filter(({ key }) => DATE_OPTION_KEYS.has(key))

export function FeatureFlagRequestUsage(): JSX.Element {
    const {
        interval,
        dateFrom,
        dateTo,
        isHourlyAvailable,
        usageResponse,
        usageResponseLoading,
        loadError,
        dates,
        series,
        sdkTotals,
        sdkOptions,
        selectedSDKs,
        requestType,
        metric,
        totalRemoteRequests,
        totalLocalRequests,
        totalBillingUnits,
        largestSdk,
    } = useValues(featureFlagRequestUsageLogic)
    const { setDates, setInterval, setSelectedSDKs, setRequestType, setMetric, downloadCsv } =
        useActions(featureFlagRequestUsageLogic)

    const columns: LemonTableColumns<FeatureFlagRequestUsageSdkTotal> = [
        {
            title: 'SDK',
            dataIndex: 'sdk',
            render: (value, row) => (
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => setSelectedSDKs([row.sdk])}
                    tooltip="Show only this SDK"
                    data-attr="feature-flag-request-usage-isolate-sdk"
                >
                    {value}
                </LemonButton>
            ),
            sorter: (a, b) => a.sdk.localeCompare(b.sdk),
        },
        {
            title: 'Remote requests',
            dataIndex: 'remoteRequests',
            align: 'right',
            render: (value) => (value ?? 0).toLocaleString(),
            sorter: (a, b) => a.remoteRequests - b.remoteRequests,
        },
        {
            title: 'Local requests',
            dataIndex: 'localRequests',
            align: 'right',
            render: (value) => (value ?? 0).toLocaleString(),
            sorter: (a, b) => a.localRequests - b.localRequests,
        },
        {
            title: 'Billing units',
            dataIndex: 'billingUnits',
            align: 'right',
            render: (value, { remoteRequests, localRequests }) => (
                <span>
                    {(value ?? 0).toLocaleString()}{' '}
                    <span className="text-secondary whitespace-nowrap">
                        ({remoteRequests.toLocaleString()} + 10 × {localRequests.toLocaleString()})
                    </span>
                </span>
            ),
            sorter: (a, b) => a.billingUnits - b.billingUnits,
        },
        {
            title: 'Share',
            dataIndex: 'billingUnitsShare',
            align: 'right',
            render: (value) => `${Number(value ?? 0).toFixed(1)}%`,
            sorter: (a, b) => a.billingUnitsShare - b.billingUnitsShare,
        },
    ]

    if (usageResponseLoading && !usageResponse) {
        return <Spinner className="m-8" />
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-2 flex-wrap">
                <div>
                    <h2 className="mb-1">Request usage</h2>
                    <p className="text-secondary m-0">Billable feature flag requests grouped by the SDK user agent.</p>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                        dateOptions={DATE_OPTIONS}
                        max={30}
                        allowedRollingDateOptions={['days']}
                        allowFixedRangeWithTime
                        allowTimePrecision
                    />
                    <span className="text-secondary">grouped by</span>
                    <IntervalFilterStandalone
                        interval={interval}
                        onIntervalChange={(value) => setInterval(value as FeatureFlagRequestUsageInterval)}
                        options={[
                            {
                                label: 'Hour',
                                value: 'hour',
                                disabledReason: isHourlyAvailable
                                    ? undefined
                                    : 'Hourly grouping is available for Last 7 days or shorter ranges.',
                            },
                            { label: 'Day', value: 'day' },
                        ]}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconDownload />}
                        onClick={downloadCsv}
                        disabledReason={sdkTotals.length === 0 ? 'No usage data to export' : undefined}
                        data-attr="feature-flag-request-usage-download-csv"
                    >
                        Download CSV
                    </LemonButton>
                </div>
            </div>

            {loadError && (
                <LemonBanner type="error">
                    Couldn't load feature flag request usage. Adjust the date range or grouping and try again. Contact
                    support if it keeps failing.
                </LemonBanner>
            )}

            <LemonBanner type="info">
                This view shows billable requests, not every HTTP request. Remote requests include <code>/flags</code>{' '}
                and legacy <code>/decide</code> traffic. Local evaluation requests use 10 billing units each. Data can
                take about 30 minutes to appear, and hourly buckets reflect billing aggregation time rather than exact
                request time.{' '}
                <Link to="https://posthog.com/docs/feature-flags/common-questions#billing--usage">
                    Learn how usage is calculated
                </Link>
                .
            </LemonBanner>

            <div className="flex items-end gap-3 flex-wrap border rounded p-3 bg-surface-primary">
                <div className="flex flex-col gap-1">
                    <LemonLabel>SDKs</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        displayMode="count"
                        bulkActions="select-and-clear-all"
                        className="w-60"
                        value={selectedSDKs}
                        onChange={setSelectedSDKs}
                        placeholder="All SDKs"
                        options={sdkOptions}
                        allowCustomValues={false}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Request type</LemonLabel>
                    <LemonSegmentedButton<FeatureFlagRequestTypeFilter>
                        size="small"
                        value={requestType}
                        onChange={setRequestType}
                        options={[
                            { value: 'all', label: 'All' },
                            { value: 'remote_evaluation', label: 'Remote' },
                            { value: 'local_evaluation', label: 'Local' },
                        ]}
                    />
                </div>
            </div>

            {!loadError && (
                <>
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                        <RequestUsageSummaryCard label="Remote requests" value={totalRemoteRequests} />
                        <RequestUsageSummaryCard label="Local requests" value={totalLocalRequests} />
                        <RequestUsageSummaryCard label="Billing units" value={totalBillingUnits} />
                        <LemonCard className="p-4">
                            <div className="text-secondary">Largest SDK contributor</div>
                            <div className="text-2xl font-semibold truncate">{largestSdk?.sdk ?? '—'}</div>
                            {largestSdk && (
                                <div className="text-secondary tabular-nums">
                                    {largestSdk.billingUnitsShare.toFixed(1)}% of billing units
                                </div>
                            )}
                        </LemonCard>
                    </div>

                    {sdkTotals.length === 0 ? (
                        <LemonBanner type="info">
                            No SDK-level request usage matches these filters. Try a wider date range or clear a filter.
                        </LemonBanner>
                    ) : (
                        <>
                            <LemonCard className="p-4">
                                <div className="flex items-center justify-between gap-2 flex-wrap">
                                    <h3 className="m-0">
                                        {metric === 'requests' ? 'Requests' : 'Billing units'} over time
                                    </h3>
                                    <LemonSegmentedButton<FeatureFlagRequestUsageMetric>
                                        size="small"
                                        value={metric}
                                        onChange={setMetric}
                                        options={[
                                            { value: 'requests', label: 'Requests' },
                                            { value: 'billing_units', label: 'Billing units' },
                                        ]}
                                    />
                                </div>
                                <BillingLineGraph
                                    series={series}
                                    dates={dates}
                                    isLoading={usageResponseLoading}
                                    hiddenSeries={[]}
                                    interval={interval}
                                    legendInteractive
                                />
                            </LemonCard>
                            <LemonTable
                                columns={columns}
                                dataSource={sdkTotals}
                                rowKey="sdk"
                                loading={usageResponseLoading}
                                defaultSorting={{ columnKey: 'billingUnits', order: -1 }}
                            />
                        </>
                    )}
                </>
            )}
        </div>
    )
}
