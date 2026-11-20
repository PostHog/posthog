import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Skeleton, Text } from '@posthog/quill'

import { QuillConfigurationSubsection } from '../QuillConfigurationSubsection'
import { QuillRateLimitChartToolbar } from './QuillRateLimitChartToolbar'
import { QuillRateLimitConfigFields } from './QuillRateLimitConfigFields'
import { rateLimitConfigLogic } from './rateLimitConfigLogic'
import { RateLimitHistoryChart } from './RateLimitHistoryChart'
import { RateLimitSimulationChart } from './RateLimitSimulationChart'

export function QuillProjectRateLimitSection(): JSX.Element {
    const {
        configLoading,
        configFormChanged,
        isConfigFormSubmitting,
        configForm,
        volume,
        volumeLoading,
        volumeBucketMinutes,
        chartMode,
        history,
        historyLoading,
    } = useValues(rateLimitConfigLogic)
    const { setChartMode, refreshChart } = useActions(rateLimitConfigLogic)
    const chartLoading = chartMode === 'history' ? historyLoading : volumeLoading

    if (configLoading) {
        return (
            <div className="flex flex-col gap-4">
                <Skeleton className="w-full h-10" />
                <Skeleton className="w-full h-64" />
            </div>
        )
    }

    return (
        <QuillConfigurationSubsection
            title="Project-wide rate limit"
            description="This limit applies across the entire project. Exceptions received above the configured rate are dropped at ingestion."
        >
            <Form logic={rateLimitConfigLogic} formKey="configForm" enableFormOnSubmit className="@container">
                <div className="grid grid-cols-1 gap-6 @3xl:grid-cols-10">
                    <div className="@3xl:col-span-3">
                        <QuillRateLimitConfigFields
                            valueFieldName="project_rate_limit_value"
                            bucketFieldName="project_rate_limit_bucket_size_minutes"
                            valueDataAttr="rate-limit-value"
                            bucketDataAttr="rate-limit-bucket-size"
                            formChanged={configFormChanged}
                            formSubmitting={isConfigFormSubmitting}
                        />
                    </div>

                    <div className="flex flex-col gap-2 @3xl:col-span-7">
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            {chartMode === 'simulation'
                                ? 'This shows your past traffic to help you choose a rate limit.'
                                : 'This shows how many exceptions were recorded vs dropped based on your rate limits.'}
                        </Text>
                        <QuillRateLimitChartToolbar
                            chartMode={chartMode}
                            onChartModeChange={setChartMode}
                            bucketMinutes={volumeBucketMinutes}
                            loading={chartLoading}
                            onRefresh={refreshChart}
                        />
                        {chartMode === 'simulation' ? (
                            volumeLoading && volume.length === 0 ? (
                                <Skeleton className="w-full h-80" />
                            ) : (
                                <RateLimitSimulationChart
                                    volume={volume}
                                    rateLimit={configForm.project_rate_limit_value}
                                    bucketMinutes={volumeBucketMinutes}
                                />
                            )
                        ) : historyLoading && history.length === 0 ? (
                            <Skeleton className="w-full h-80" />
                        ) : (
                            <RateLimitHistoryChart history={history} bucketMinutes={volumeBucketMinutes} />
                        )}
                    </div>
                </div>
            </Form>
        </QuillConfigurationSubsection>
    )
}
