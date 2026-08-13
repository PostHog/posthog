import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonCard, LemonSelect, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { DefaultTooltip, type Series, TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { getColorVar } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { LogsAlertSimulateBucketApi, LogsAlertSimulateResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertFormLogic } from './logsAlertFormLogic'

const SIMULATION_RANGE_OPTIONS = [
    { value: '-1h', label: 'Last 1 hour' },
    { value: '-6h', label: 'Last 6 hours' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
]

function BucketTooltipDetails({ bucket }: { bucket: LogsAlertSimulateBucketApi | undefined }): JSX.Element | null {
    if (!bucket) {
        return null
    }
    const details = [`State: ${bucket.state}`]
    if (bucket.threshold_breached) {
        details.push('Threshold breached')
    }
    if (bucket.notification === 'fire') {
        details.push('Notification sent')
    } else if (bucket.notification === 'resolve') {
        details.push('Resolved notification sent')
    }
    return (
        <div className="flex flex-col text-left">
            {details.map((detail) => (
                <span key={detail}>{detail}</span>
            ))}
        </div>
    )
}

function SimulationChart({ result }: { result: LogsAlertSimulateResponseApi }): JSX.Element {
    const { labels, series } = useMemo(
        () => ({
            labels: result.buckets.map((b: LogsAlertSimulateBucketApi) => b.timestamp),
            series: [
                {
                    key: 'count',
                    label: 'Log count',
                    data: result.buckets.map((b: LogsAlertSimulateBucketApi) => b.count),
                    // One series with per-bar colors, so a bucket's simulated outcome is visible without
                    // splitting the counts across three mutually exclusive series.
                    bars: result.buckets.map((b: LogsAlertSimulateBucketApi) => {
                        if (b.notification === 'fire') {
                            return { color: getColorVar('danger') }
                        }
                        return b.threshold_breached ? { color: getColorVar('warning') } : {}
                    }),
                },
            ] as Series[],
        }),
        [result]
    )

    const theme = useChartTheme()
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            showCrosshair: false,
            // Buckets are minutes apart, and the surrounding incident table renders in local time.
            xAxis: { interval: 'minute', timezone: dayjs.tz.guess() },
            goalLines: [
                {
                    value: result.threshold_count,
                    label: 'Threshold',
                    displayLabel: true,
                },
            ],
        }),
        [result.threshold_count]
    )

    return (
        // Quill charts fill a *flex* parent (their root is flex-1), so the sized container must be a flex column.
        <div className="h-56 flex flex-col">
            <TimeSeriesBarChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                tooltip={(ctx) => (
                    <DefaultTooltip
                        {...ctx}
                        labelFormatter={(label) => dayjs(label).format('MMM D, HH:mm')}
                        footer={<BucketTooltipDetails bucket={result.buckets[ctx.dataIndex]} />}
                    />
                )}
            />
        </div>
    )
}

interface Incident {
    firedAt: string
    resolvedAt: string | null
    durationMinutes: number
    peakCount: number
    stillFiring: boolean
}

function extractIncidents(buckets: LogsAlertSimulateBucketApi[]): Incident[] {
    const incidents: Incident[] = []
    let currentIncident: Incident | null = null

    for (const b of buckets) {
        if (b.state === 'firing' || b.state === 'pending_resolve') {
            if (!currentIncident) {
                currentIncident = {
                    firedAt: b.timestamp,
                    resolvedAt: null,
                    durationMinutes: 1,
                    peakCount: b.count,
                    stillFiring: true,
                }
            } else {
                currentIncident.durationMinutes += 1
                currentIncident.peakCount = Math.max(currentIncident.peakCount, b.count)
            }
        } else if (currentIncident) {
            currentIncident.resolvedAt = b.timestamp
            currentIncident.stillFiring = false
            incidents.push(currentIncident)
            currentIncident = null
        }
    }
    if (currentIncident) {
        incidents.push(currentIncident)
    }
    return incidents
}

function SimulationSummary({
    result,
    incidents,
}: {
    result: LogsAlertSimulateResponseApi
    incidents: Incident[]
}): JSX.Element {
    const totalFiringSeconds = incidents.reduce((sum, inc) => sum + inc.durationMinutes * 60, 0)

    return (
        <div className="flex gap-6 py-2">
            <div>
                <Tooltip title="Number of times this alert would have fired and sent a notification">
                    <div className="text-xs text-secondary cursor-help">Alerts</div>
                </Tooltip>
                <div className={`text-lg font-semibold ${result.fire_count > 0 ? 'text-danger' : ''}`}>
                    {result.fire_count}
                </div>
            </div>
            <div>
                <Tooltip title="Total time the alert would have been in a firing state">
                    <div className="text-xs text-secondary cursor-help">Total firing time</div>
                </Tooltip>
                <div className="text-lg font-semibold">
                    {totalFiringSeconds > 0 ? humanFriendlyDuration(totalFiringSeconds) : '0m'}
                </div>
            </div>
            <div>
                <Tooltip title="Number of times the alert resolved after firing">
                    <div className="text-xs text-secondary cursor-help">Resolutions</div>
                </Tooltip>
                <div className="text-lg font-semibold">{result.resolve_count}</div>
            </div>
        </div>
    )
}

function SimulationIncidents({
    incidents,
    threshold,
}: {
    incidents: Incident[]
    threshold: number
}): JSX.Element | null {
    if (incidents.length === 0) {
        return null
    }

    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center bg-bg-light text-xs font-semibold text-secondary py-2">
                <Tooltip title="When the alert first breached the threshold and sent a notification">
                    <div className="flex-[3] min-w-0 px-3 cursor-help">Started</div>
                </Tooltip>
                <Tooltip title="How long the alert remained in a firing state">
                    <div className="flex-[1] min-w-0 px-2 cursor-help">Duration</div>
                </Tooltip>
                <Tooltip title="Highest rolling window count during this alert vs your configured threshold">
                    <div className="flex-[1] min-w-0 px-2 cursor-help">Peak / threshold</div>
                </Tooltip>
                <Tooltip title="Whether the alert resolved or is still active at the end of the simulation window">
                    <div className="flex-[3] min-w-0 px-2 cursor-help">Outcome</div>
                </Tooltip>
            </div>
            <div className="max-h-[280px] overflow-y-auto divide-y divide-border">
                {incidents.map((incident, i) => {
                    const peakRatio = incident.peakCount / threshold
                    const severityColor =
                        peakRatio >= 5 ? 'text-danger font-bold' : peakRatio >= 2 ? 'text-danger' : 'text-warning'

                    return (
                        <div key={i} className="flex items-center text-xs py-2.5">
                            <div className="flex-[3] min-w-0 px-3 font-medium">
                                <TZLabel time={incident.firedAt} timestampStyle="absolute" />
                            </div>
                            <div className="flex-[1] min-w-0 px-2">
                                {humanFriendlyDuration(incident.durationMinutes * 60)}
                            </div>
                            <div className="flex-[1] min-w-0 px-2">
                                <span className={severityColor}>{incident.peakCount.toLocaleString()}</span>
                                <span className="text-secondary"> / {threshold.toLocaleString()}</span>
                            </div>
                            <div className="flex-[3] min-w-0 px-2">
                                {incident.stillFiring ? (
                                    <LemonTag type="danger" size="small">
                                        Still firing
                                    </LemonTag>
                                ) : (
                                    <span className="text-secondary">
                                        Resolved at <TZLabel time={incident.resolvedAt!} timestampStyle="absolute" />
                                    </span>
                                )}
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

function SimulationResults({ result }: { result: LogsAlertSimulateResponseApi }): JSX.Element {
    const incidents = extractIncidents(result.buckets)
    const op = result.threshold_operator === 'above' ? '>' : '<'

    return (
        <div className="space-y-4">
            <p className="text-xs text-secondary m-0">
                Simulated with current form settings: {op} {result.threshold_count} logs in window. Edit the form and
                re-run to compare.
            </p>
            <SimulationChart result={result} />
            <SimulationSummary result={result} incidents={incidents} />
            <SimulationIncidents incidents={incidents} threshold={result.threshold_count} />
        </div>
    )
}

function SimulationPlaceholder(): JSX.Element {
    return (
        <div className="relative h-56 overflow-hidden rounded border border-dashed border-border bg-bg-light">
            <div aria-hidden className="space-y-4 p-4 opacity-60">
                <LemonSkeleton className="h-32" />
                <div className="flex gap-6">
                    <LemonSkeleton className="h-8 w-16" repeat={3} />
                </div>
            </div>
            <div className="absolute inset-0 flex items-center justify-center bg-bg-light/80 p-4 text-center">
                <div>
                    <div className="text-sm font-medium">Select a time range, then run a simulation</div>
                    <p className="m-0 mt-1 text-xs text-secondary">
                        Historical log counts and alert outcomes will appear here.
                    </p>
                </div>
            </div>
        </div>
    )
}

export function LogsAlertSimulation({ embedded = false }: { embedded?: boolean }): JSX.Element {
    const { simulationResult, simulationResultLoading, simulationDateFrom } = useValues(logsAlertFormLogic)
    const { simulateAlert, setSimulationDateFrom } = useActions(logsAlertFormLogic)

    const simulation = (
        <div className="space-y-4">
            {embedded ? (
                <div>
                    <h4 className="m-0">Preview</h4>
                    <p className="m-0 text-xs text-secondary">Check how this alert would behave on historical data.</p>
                </div>
            ) : null}
            <div className="flex gap-2 items-center">
                <LemonSelect
                    size="small"
                    value={simulationDateFrom}
                    onChange={(value) => setSimulationDateFrom(value)}
                    options={SIMULATION_RANGE_OPTIONS}
                />
                <LemonButton type="primary" size="small" onClick={simulateAlert} loading={simulationResultLoading}>
                    Run simulation
                </LemonButton>
            </div>

            {simulationResultLoading && !simulationResult && (
                <div className="space-y-3">
                    <LemonSkeleton className="h-56" />
                    <LemonSkeleton className="h-8" repeat={3} />
                </div>
            )}

            {simulationResult && <SimulationResults result={simulationResult} />}

            {!simulationResult && !simulationResultLoading && <SimulationPlaceholder />}
        </div>
    )

    if (embedded) {
        return (
            <LemonCard className="p-4" hoverEffect={false}>
                {simulation}
            </LemonCard>
        )
    }

    return <div className="p-4">{simulation}</div>
}
