import { LemonLabel, SpinnerOverlay } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { type AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricSummary } from 'lib/components/AppMetrics/AppMetricSummary'
import { humanFriendlyNumber } from 'lib/utils'

interface ConversionRatesSectionProps {
    loading: boolean
    conversionRate: number
    conversionTotal: number
    startedTotal: number
    conversionRateSeries: AppMetricsTimeSeriesResponse | null
    earlyExitSeries: AppMetricsTimeSeriesResponse | null
    earlyExitPreviousPeriodSeries: AppMetricsTimeSeriesResponse | null
}

export function ConversionRatesSection({
    loading,
    conversionRate,
    conversionTotal,
    startedTotal,
    earlyExitSeries,
    earlyExitPreviousPeriodSeries,
}: ConversionRatesSectionProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2 mt-2">
            <LemonLabel className="text-sm font-semibold">Conversion</LemonLabel>
            <div className="flex flex-row gap-2 flex-wrap justify-center">
                <div className="flex flex-1 flex-col relative border rounded p-3 bg-surface-primary min-w-[16rem]">
                    <div className="flex flex-col h-full">
                        <LemonLabel info="Percentage of started workflows that converted (exited early due to conversion goal being met)">
                            Conversion rate
                        </LemonLabel>
                        <div className="flex flex-1 items-center justify-center">
                            {loading ? (
                                <SpinnerOverlay />
                            ) : (
                                <div className="flex flex-col items-center">
                                    <div className="text-6xl text-muted-foreground mb-2">{conversionRate}%</div>
                                    <div className="text-xs text-muted">
                                        {humanFriendlyNumber(conversionTotal)} of {humanFriendlyNumber(startedTotal)}{' '}
                                        started
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                <AppMetricSummary
                    name="Converted"
                    description="Total number of workflow runs that exited early because the conversion goal was met"
                    loading={loading}
                    timeSeries={earlyExitSeries}
                    previousPeriodTimeSeries={earlyExitPreviousPeriodSeries}
                    color={getColorVar('success')}
                    colorIfZero={getColorVar('muted')}
                />
            </div>
        </div>
    )
}
