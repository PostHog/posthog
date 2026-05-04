import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { pluralize } from 'lib/utils'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

import { BUCKET_OPTIONS, ExceptionVolumeBucket, getBucketOption, rateLimitConfigLogic } from './rateLimitConfigLogic'

export function RateLimitSettings(): JSX.Element {
    const {
        configLoading,
        configFormChanged,
        isConfigFormSubmitting,
        configForm,
        volume,
        volumeLoading,
        volumeBucketMinutes,
    } = useValues(rateLimitConfigLogic)

    if (configLoading) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="w-full h-10" />
                <LemonSkeleton className="w-full h-64" />
            </div>
        )
    }

    return (
        <div className="space-y-4">
            <div>
                <h3 className="font-semibold text-base mb-1">Project-wide rate limit</h3>
                <p className="text-muted-foreground">
                    This limit applies across the entire project. Exceptions received above the configured rate are
                    dropped at ingestion.
                </p>
            </div>

            <Form logic={rateLimitConfigLogic} formKey="configForm" enableFormOnSubmit>
                <div className="grid grid-cols-1 md:grid-cols-10 gap-6">
                    <div className="md:col-span-3 space-y-3">
                        <LemonField name="project_rate_limit_value" label="Maximum exceptions">
                            {({ value, onChange }) => (
                                <LemonInput
                                    type="number"
                                    min={1}
                                    value={value ?? undefined}
                                    onChange={(v) => onChange(v ?? null)}
                                    placeholder="Unlimited"
                                    fullWidth
                                    data-attr="rate-limit-value"
                                />
                            )}
                        </LemonField>

                        <LemonField name="project_rate_limit_bucket_size_minutes" label="Per">
                            {({ value, onChange }) => (
                                <LemonSelect
                                    value={value}
                                    onChange={onChange}
                                    options={BUCKET_OPTIONS.map((o) => ({ label: o.label, value: o.minutes }))}
                                    fullWidth
                                    data-attr="rate-limit-bucket-size"
                                />
                            )}
                        </LemonField>

                        <p className="text-muted-foreground text-xs">
                            The maximum number of exceptions accepted per time window. Leave the value empty for no
                            limit.
                        </p>

                        <div className="flex justify-start pt-2">
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                disabledReason={!configFormChanged ? 'No changes to save' : undefined}
                                loading={isConfigFormSubmitting}
                            >
                                Save
                            </LemonButton>
                        </div>
                    </div>

                    <div className="md:col-span-7">
                        <div className="text-sm font-medium mb-1">
                            Exception volume — past {formatTotalDuration(volumeBucketMinutes)}
                        </div>
                        {volumeLoading ? (
                            <LemonSkeleton className="w-full h-80" />
                        ) : (
                            <RateLimitSimulationChart
                                volume={volume}
                                rateLimit={configForm.project_rate_limit_value}
                                bucketMinutes={volumeBucketMinutes}
                            />
                        )}
                    </div>
                </div>
            </Form>
        </div>
    )
}

function formatTotalDuration(bucketMinutes: number): string {
    const option = getBucketOption(bucketMinutes)
    const totalMinutes = option.minutes * option.bucketCount
    if (totalMinutes >= 10080) {
        return pluralize(Math.round(totalMinutes / 10080), 'week')
    }
    if (totalMinutes >= 1440) {
        return pluralize(Math.round(totalMinutes / 1440), 'day')
    }
    return pluralize(Math.round(totalMinutes / 60), 'hour')
}

function fillBuckets(volume: ExceptionVolumeBucket[], bucketMinutes: number): ExceptionVolumeBucket[] {
    const option = getBucketOption(bucketMinutes)
    const bucketMs = option.minutes * 60_000
    const counts = new Map<number, number>()
    volume.forEach((b) => {
        const aligned = Math.floor(dayjs(b.bucket).valueOf() / bucketMs) * bucketMs
        counts.set(aligned, b.count)
    })
    const endMs = Math.floor(Date.now() / bucketMs) * bucketMs
    const buckets: ExceptionVolumeBucket[] = []
    for (let i = option.bucketCount - 1; i >= 0; i--) {
        const ms = endMs - i * bucketMs
        buckets.push({ bucket: dayjs(ms).toISOString(), count: counts.get(ms) ?? 0 })
    }
    return buckets
}

function formatBucketLabel(iso: string, bucketMinutes: number): string {
    const ts = dayjs(iso)
    if (bucketMinutes >= 1440) {
        return ts.format('MMM D')
    }
    return ts.format('MMM D, HH:mm')
}

function RateLimitSimulationChart({
    volume,
    rateLimit,
    bucketMinutes,
}: {
    volume: ExceptionVolumeBucket[]
    rateLimit: number | null
    bucketMinutes: number
}): JSX.Element {
    const { xData, yData } = useMemo(() => {
        const filled = fillBuckets(volume, bucketMinutes)
        const labels = filled.map((b) => formatBucketLabel(b.bucket, bucketMinutes))
        const counts = filled.map((b) => b.count)
        return {
            xData: {
                column: {
                    name: 'bucket',
                    type: { name: 'STRING' as const, isNumerical: false },
                    label: 'Bucket',
                    dataIndex: 0,
                },
                data: labels,
            },
            yData: [
                {
                    column: {
                        name: 'count',
                        type: { name: 'INTEGER' as const, isNumerical: true },
                        label: 'Exceptions',
                        dataIndex: 0,
                    },
                    data: counts,
                    settings: {
                        display: {
                            displayType: 'bar' as const,
                        },
                    },
                },
            ],
        }
    }, [volume, bucketMinutes])

    const goalLines = useMemo(() => {
        if (!rateLimit || rateLimit <= 0) {
            return []
        }
        const option = getBucketOption(bucketMinutes)
        return [
            {
                label: `Limit: ${rateLimit} per ${option.label}`,
                value: rateLimit,
                displayLabel: true,
            },
        ]
    }, [rateLimit, bucketMinutes])

    return (
        <div className="h-80 border rounded">
            <LineGraph
                className="h-full p-4"
                xData={xData}
                yData={yData}
                visualizationType={ChartDisplayType.ActionsBar}
                chartSettings={{ showXAxisTicks: false, showXAxisBorder: false }}
                goalLines={goalLines}
            />
        </div>
    )
}
