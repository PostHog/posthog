import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { AppMetricsFilters } from 'lib/components/AppMetrics/AppMetricsFilters'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'
import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { capitalizeFirstLetter } from 'lib/utils'

import { campaignLogic } from './campaignLogic'
import { getHogFlowStep } from './hogflows/steps/HogFlowSteps'

export const CAMPAIGN_METRICS_INFO: Record<string, { description: string; color: string }> = {
    succeeded: {
        description: 'Total number of events processed successfully',
        color: getColorVar('success'),
    },
    failed: {
        description: 'Total number of events that had errors during processing',
        color: getColorVar('danger'),
    },
    filtered: {
        description: 'Total number of events that were filtered out',
        color: getColorVar('muted'),
    },
    disabled: {
        description:
            'Total number of events that were skipped due to the destination being permanently disabled (due to prolonged issues with the destination)',
        color: getColorVar('danger'),
    },
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

    const { campaign, hogFunctionTemplatesById } = useValues(campaignLogic({ id }))

    const { appMetricsTrendsLoading, getSingleTrendSeries, appMetricsTrends, params } = useValues(logic)
    const { setParams } = useActions(logic)

    const modifiedAppMetricsTrends = useMemo(
        () =>
            appMetricsTrends
                ? {
                      ...appMetricsTrends,
                      series: appMetricsTrends.series.map((series) => ({
                          ...series,
                          color: CAMPAIGN_METRICS_INFO[series.name as keyof typeof CAMPAIGN_METRICS_INFO]?.color,
                      })),
                  }
                : null,
        [appMetricsTrends]
    )

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
                                options: campaign.actions.map((action) => {
                                    const Step = getHogFlowStep(action, hogFunctionTemplatesById)
                                    return {
                                        label: (
                                            <span className="flex items-center gap-1">
                                                {Step?.icon} {action.name}
                                            </span>
                                        ),
                                        value: action.id,
                                    }
                                }),
                            },
                        ]}
                        value={params.instanceId ?? null}
                        onChange={(value) => setParams({ ...params, instanceId: value ?? undefined })}
                    />
                </div>
                <AppMetricsFilters logicKey={logicKey} />
            </div>

            <div className="flex flex-row gap-2 flex-wrap justify-center">
                {Object.entries(CAMPAIGN_METRICS_INFO).map(([key, metric]) => (
                    <AppMetricSummary
                        name={capitalizeFirstLetter(key)}
                        description={metric.description}
                        loading={appMetricsTrendsLoading}
                        timeSeries={getSingleTrendSeries(key)}
                        previousPeriodTimeSeries={getSingleTrendSeries(key, true)}
                        color={metric.color}
                        colorIfZero={getColorVar('muted')}
                    />
                ))}
            </div>

            <AppMetricsTrends appMetricsTrends={modifiedAppMetricsTrends} loading={appMetricsTrendsLoading} />
        </div>
    )
}
