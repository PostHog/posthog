import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'

import { campaignLogic } from './campaignLogic'
import { getHogFlowStep } from './hogflows/steps/HogFlowSteps'

const METRICS_INFO = {
    succeeded: 'Total number of events processed successfully',
    failed: 'Total number of events that had errors during processing',
    filtered: 'Total number of events that were filtered out',
    disabled:
        'Total number of events that were skipped due to the destination being permanently disabled (due to prolonged issues with the destination)',
}

export type CampaignMetricsProps = {
    id: string
}

export function CampaignMetrics({ id }: CampaignMetricsProps): JSX.Element {
    const logicKey = `hog-flow-metrics-${id}`

    const logic = appMetricsLogic({
        logicKey,
        loadOnChanges: true,
        forceParams: {
            appSource: 'hog_flow',
            appSourceId: id,
            // metricName: ['succeeded', 'failed', 'filtered', 'disabled_permanently'],
            breakdownBy: 'metric_name',
        },
    })

    const { campaign } = useValues(campaignLogic({ id }))

    const { appMetricsTrendsLoading, getSingleTrendSeries, appMetricsTrends, params } = useValues(logic)
    const { setParams } = useActions(logic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-row gap-2 flex-wrap justify-between">
                <div>
                    <LemonSelect
                        size="small"
                        options={[
                            {
                                title: 'Workflow',
                                options: [
                                    {
                                        label: 'Overview',
                                        value: null,
                                    },
                                ],
                            },
                            {
                                title: 'Workflow steps',
                                options: campaign.actions.map((action) => ({
                                    label: (
                                        <span className="flex items-center gap-1">
                                            {getHogFlowStep(action.type)?.icon} {getHogFlowStep(action.type)?.name}
                                        </span>
                                    ),
                                    value: action.id,
                                })),
                            },
                        ]}
                        value={params.instanceId ?? null}
                        onChange={(value) => setParams({ ...params, instanceId: value ?? undefined })}
                    />
                </div>
                <AppMetricsFilters logicKey={logicKey} />
            </div>

            <div className="flex flex-row gap-2 flex-wrap justify-center">
                <AppMetricSummary
                    name="Success"
                    description={METRICS_INFO.succeeded}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('succeeded')}
                    previousPeriodTimeSeries={getSingleTrendSeries('succeeded', true)}
                />

                <AppMetricSummary
                    name="Failure"
                    description={METRICS_INFO.failed}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('failed')}
                    previousPeriodTimeSeries={getSingleTrendSeries('failed', true)}
                />

                <AppMetricSummary
                    name="Filtered"
                    description={METRICS_INFO.filtered}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('filtered')}
                    previousPeriodTimeSeries={getSingleTrendSeries('filtered', true)}
                />

                <AppMetricSummary
                    name="Disabled"
                    description={METRICS_INFO.disabled}
                    loading={appMetricsTrendsLoading}
                    timeSeries={getSingleTrendSeries('disabled_permanently')}
                    previousPeriodTimeSeries={getSingleTrendSeries('disabled_permanently', true)}
                />
            </div>

            <AppMetricsTrends appMetricsTrends={appMetricsTrends} loading={appMetricsTrendsLoading} />
        </div>
    )
}
