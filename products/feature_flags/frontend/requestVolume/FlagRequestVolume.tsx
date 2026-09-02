import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonTable, Link, Tooltip } from '@posthog/lemon-ui'

import { AppMetricsTimeSeriesChart } from 'lib/components/AppMetrics/AppMetricsTimeSeriesChart'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { FlagRequestsVolumeRetrieveBreakdown } from '../generated/api.schemas'
import { FlagRequestVolumeTotal, flagRequestVolumeLogic } from './flagRequestVolumeLogic'

const REQUEST_TYPE_LABELS: Record<string, string> = {
    decide: 'Remote evaluation',
    'local-evaluation': 'Local evaluation',
    'remote-config': 'Remote config',
}

const UNATTRIBUTED = 'unattributed'

const BILLING_USAGE_URL = `${urls.organizationBillingSection(
    'usage'
)}?usage_types=billable_feature_flag_requests_count_in_period`

function seriesLabel(name: string): string {
    if (name === UNATTRIBUTED) {
        return 'Unattributed'
    }
    return REQUEST_TYPE_LABELS[name] ?? name
}

export function FlagRequestVolume(): JSX.Element {
    const { breakdown, dateFrom, dateTo, requestVolume, requestVolumeLoading, totals, hasRequests } =
        useValues(flagRequestVolumeLogic)
    const { setBreakdown, setDates } = useActions(flagRequestVolumeLogic)

    const localEvaluationWeight = requestVolume?.billing_weights['local-evaluation']
    const showBillable = breakdown === FlagRequestsVolumeRetrieveBreakdown.RequestType

    return (
        <div className="flex flex-col gap-4" data-attr="feature-flag-request-volume">
            <p className="mb-0">
                Requests your SDKs made to evaluate flags.{' '}
                {localEvaluationWeight !== undefined && localEvaluationWeight > 1 ? (
                    <>
                        A local evaluation request counts as {localEvaluationWeight} requests, because one poll returns
                        the definitions of every flag in this project.{' '}
                    </>
                ) : null}
                <Link to={BILLING_USAGE_URL} data-attr="feature-flag-request-volume-billing-link">
                    See your billed total
                </Link>
                .
            </p>

            <div className="flex flex-wrap items-center gap-2">
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={(from, to) => setDates(from ?? '-7d', to ?? '-0d')}
                />
                <LemonSegmentedButton
                    size="small"
                    value={breakdown}
                    onChange={setBreakdown}
                    options={[
                        { value: FlagRequestsVolumeRetrieveBreakdown.RequestType, label: 'By request type' },
                        { value: FlagRequestsVolumeRetrieveBreakdown.Library, label: 'By SDK' },
                    ]}
                    data-attr="feature-flag-request-volume-breakdown"
                />
            </div>

            {requestVolumeLoading ? (
                <LemonSkeleton className="h-64 w-full" />
            ) : !hasRequests ? (
                <p className="mb-0 text-secondary">
                    No flag requests recorded in this range. This project records the breakdown from the point it was
                    turned on, so earlier requests are not shown here.
                </p>
            ) : (
                <>
                    {requestVolume ? (
                        <AppMetricsTimeSeriesChart
                            className="h-64"
                            timeSeries={{
                                labels: requestVolume.labels,
                                series: requestVolume.series.map((series) => ({
                                    name: seriesLabel(series.name),
                                    values: series.values,
                                })),
                            }}
                            showLegend
                        />
                    ) : null}
                    <LemonTable
                        dataSource={totals}
                        columns={[
                            {
                                title: showBillable ? 'Request type' : 'SDK',
                                dataIndex: 'name',
                                render: (_, total: FlagRequestVolumeTotal) =>
                                    total.name === UNATTRIBUTED ? (
                                        <Tooltip title="The flags service could not tell which SDK sent these requests.">
                                            <span>{seriesLabel(total.name)}</span>
                                        </Tooltip>
                                    ) : (
                                        seriesLabel(total.name)
                                    ),
                            },
                            {
                                title: 'Requests',
                                dataIndex: 'requests',
                                align: 'right',
                                render: (_, total: FlagRequestVolumeTotal) => humanFriendlyNumber(total.requests),
                            },
                            ...(showBillable
                                ? [
                                      {
                                          title: 'Billable requests',
                                          dataIndex: 'billableRequests' as const,
                                          align: 'right' as const,
                                          render: (_: any, total: FlagRequestVolumeTotal) =>
                                              humanFriendlyNumber(total.billableRequests),
                                      },
                                  ]
                                : []),
                        ]}
                    />
                </>
            )}
        </div>
    )
}
