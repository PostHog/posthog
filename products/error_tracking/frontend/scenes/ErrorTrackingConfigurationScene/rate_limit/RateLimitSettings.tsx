import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo } from 'react'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { LineGraph } from '~/queries/nodes/DataVisualization/Components/Charts/LineGraph'
import { ChartDisplayType } from '~/types'

import { ExceptionVolumeBucket, rateLimitConfigLogic } from './rateLimitConfigLogic'

const SIMULATION_HOURS = 7 * 24

export function RateLimitSettings(): JSX.Element {
    const { configLoading, configFormChanged, isConfigFormSubmitting, configForm, volume, volumeLoading } =
        useValues(rateLimitConfigLogic)

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
                <h3 className="font-semibold text-base mb-1">Project wide rate limit</h3>
                <p className="text-muted-foreground">
                    This limit applies across the entire project. Exceptions received above the configured hourly rate
                    are dropped at ingestion.
                </p>
            </div>

            <Form logic={rateLimitConfigLogic} formKey="configForm" enableFormOnSubmit>
                <div className="grid grid-cols-1 md:grid-cols-10 gap-6">
                    <div className="md:col-span-3 space-y-2">
                        <LemonField name="rate_limit_per_hour" label="Exceptions per hour">
                            {({ value, onChange }) => (
                                <LemonInput
                                    type="number"
                                    min={1}
                                    value={value ?? undefined}
                                    onChange={(v) => onChange(v ?? null)}
                                    placeholder="Unlimited"
                                    fullWidth
                                    data-attr="rate-limit-per-hour"
                                />
                            )}
                        </LemonField>
                        <p className="text-muted-foreground text-xs">
                            The maximum number of exceptions accepted each hour. Leave empty for no limit.
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
                        <div className="text-sm font-medium mb-1">Hourly exception volume — last 7 days</div>
                        {volumeLoading ? (
                            <LemonSkeleton className="w-full h-64" />
                        ) : (
                            <RateLimitSimulationChart volume={volume} rateLimit={configForm.rate_limit_per_hour} />
                        )}
                    </div>
                </div>
            </Form>
        </div>
    )
}

function fillHourlyBuckets(volume: ExceptionVolumeBucket[]): ExceptionVolumeBucket[] {
    const counts = new Map(volume.map((b) => [dayjs(b.hour).startOf('hour').toISOString(), b.count]))
    const end = dayjs().startOf('hour')
    const start = end.subtract(SIMULATION_HOURS - 1, 'hour')
    const buckets: ExceptionVolumeBucket[] = []
    for (let i = 0; i < SIMULATION_HOURS; i++) {
        const ts = start.add(i, 'hour')
        const key = ts.toISOString()
        buckets.push({ hour: ts.toISOString(), count: counts.get(key) ?? 0 })
    }
    return buckets
}

function RateLimitSimulationChart({
    volume,
    rateLimit,
}: {
    volume: ExceptionVolumeBucket[]
    rateLimit: number | null
}): JSX.Element {
    const { xData, yData } = useMemo(() => {
        const filled = fillHourlyBuckets(volume)
        const labels = filled.map((b) => dayjs(b.hour).format('MMM D, HH:mm'))
        const counts = filled.map((b) => b.count)
        return {
            xData: {
                column: {
                    name: 'hour',
                    type: { name: 'STRING' as const, isNumerical: false },
                    label: 'Hour',
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
    }, [volume])

    const goalLines = useMemo(
        () =>
            rateLimit && rateLimit > 0
                ? [
                      {
                          label: `Limit: ${rateLimit}/hour`,
                          value: rateLimit,
                          displayLabel: true,
                      },
                  ]
                : [],
        [rateLimit]
    )

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
