import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useChart } from 'lib/hooks/useChart'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils'

import { LogsAlertSimulateBucketApi, LogsAlertSimulateResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { logsAlertFormLogic } from './logsAlertFormLogic'

const SIMULATION_RANGE_OPTIONS = [
    { value: '-1h', label: 'Last 1 hour' },
    { value: '-6h', label: 'Last 6 hours' },
    { value: '-24h', label: 'Last 24 hours' },
    { value: '-7d', label: 'Last 7 days' },
]

const CHART_COLORS = {
    normal: { bg: 'rgba(99, 102, 241, 0.6)', border: 'rgba(67, 56, 202, 1)' },
    breached: { bg: 'rgba(245, 158, 11, 0.6)', border: 'rgba(180, 83, 9, 1)' },
    fired: { bg: 'rgba(220, 38, 38, 0.7)', border: 'rgba(153, 27, 27, 1)' },
    threshold: { border: 'rgba(220, 38, 38, 0.5)' },
} as const

function SimulationChart({ result }: { result: LogsAlertSimulateResponseApi }): JSX.Element {
    const { canvasRef } = useChart({
        getConfig: () => ({
            type: 'bar' as const,
            data: {
                labels: result.buckets.map((b: LogsAlertSimulateBucketApi) =>
                    dayjs(b.timestamp).format('MMM D, HH:mm')
                ),
                datasets: [
                    {
                        label: 'Log count',
                        data: result.buckets.map((b: LogsAlertSimulateBucketApi) => b.count),
                        backgroundColor: result.buckets.map((b: LogsAlertSimulateBucketApi) =>
                            b.notification === 'fire'
                                ? CHART_COLORS.fired.bg
                                : b.threshold_breached
                                  ? CHART_COLORS.breached.bg
                                  : CHART_COLORS.normal.bg
                        ),
                        borderColor: result.buckets.map((b: LogsAlertSimulateBucketApi) =>
                            b.notification === 'fire'
                                ? CHART_COLORS.fired.border
                                : b.threshold_breached
                                  ? CHART_COLORS.breached.border
                                  : CHART_COLORS.normal.border
                        ),
                        borderWidth: 1,
                    },
                    {
                        label: `Threshold (${result.threshold_count})`,
                        data: Array(result.buckets.length).fill(result.threshold_count),
                        type: 'line' as const,
                        borderColor: CHART_COLORS.threshold.border,
                        borderWidth: 1.5,
                        borderDash: [4, 4],
                        pointRadius: 0,
                        fill: false,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    crosshair: false,
                    legend: {
                        display: true,
                        position: 'bottom' as const,
                        labels: {
                            boxWidth: 8,
                            boxHeight: 2,
                            font: { size: 10 },
                            padding: 8,
                        },
                    },
                    tooltip: {
                        enabled: true,
                        callbacks: {
                            label: (ctx) => {
                                const bucket = result.buckets[ctx.dataIndex]
                                if (!bucket) {
                                    return `Count: ${ctx.parsed.y}`
                                }
                                const lines = [`Count: ${ctx.parsed.y}`, `State: ${bucket.state}`]
                                if (bucket.threshold_breached) {
                                    lines.push('Threshold breached')
                                }
                                if (bucket.notification === 'fire') {
                                    lines.push('Notification sent')
                                } else if (bucket.notification === 'resolve') {
                                    lines.push('Resolved notification sent')
                                }
                                return lines
                            },
                        },
                    },
                },
                scales: {
                    x: {
                        display: true,
                        ticks: { maxTicksLimit: 12, font: { size: 10 }, maxRotation: 45 },
                    },
                    y: {
                        display: true,
                        beginAtZero: true,
                        ticks: { maxTicksLimit: 5, font: { size: 10 } },
                        grid: { drawTicks: false },
                    },
                },
            },
        }),
        deps: [result],
    })

    return (
        <div className="h-56">
            <canvas ref={canvasRef} />
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

function SimulationIncidents({ incidents, threshold }: { incidents: Incident[]; threshold: number }): JSX.Element {
    if (incidents.length === 0) {
        return (
            <div className="text-center py-4 text-secondary text-sm border rounded">
                No alerts — the alert would not have fired during this period.
                {threshold > 0 && ' Consider lowering the threshold.'}
            </div>
        )
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

export function LogsAlertSimulation(): JSX.Element {
    const { simulationResult, simulationResultLoading, simulationDateFrom } = useValues(logsAlertFormLogic)
    const { simulateAlert, setSimulationDateFrom } = useActions(logsAlertFormLogic)

    return (
        <div className="space-y-4 p-4">
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

            {!simulationResult && !simulationResultLoading && (
                <div className="text-center py-8 text-secondary text-sm">
                    Select a time range and click "Run simulation" to preview how this alert would behave on historical
                    data.
                </div>
            )}
        </div>
    )
}
