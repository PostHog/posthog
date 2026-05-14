import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import { DailyBucket, DailyStatus, Incident, MonitorStatus, MonitorSummary } from '../uptimeSceneLogic'

interface StatusPagePreviewProps {
    title: string
    monitors: MonitorSummary[]
    publishedAt?: string | null
    ongoingIncidents?: Incident[]
    recentIncidents?: Incident[]
    placeholder?: string
}

export function StatusPagePreview({
    title,
    monitors,
    publishedAt,
    ongoingIncidents = [],
    recentIncidents = [],
    placeholder = 'Add monitors from the left to see them here.',
}: StatusPagePreviewProps): JSX.Element {
    const overallStatus = computeOverallStatus(monitors)
    const monitorNameById = new Map(monitors.map((m) => [m.id, m.name]))

    return (
        <div className="flex flex-col gap-6 w-full max-w-2xl mx-auto">
            <header className="flex flex-col gap-2">
                <h1 className="text-2xl font-semibold text-primary">{title || 'Untitled status page'}</h1>
                {publishedAt && (
                    <div className="text-xs text-secondary">
                        Last updated {dayjs(publishedAt).format('MMM D, YYYY h:mm A')}
                    </div>
                )}
            </header>

            {ongoingIncidents.length > 0 && (
                <section className="flex flex-col gap-2">
                    <h2 className="text-sm font-semibold text-primary m-0">Ongoing declared incidents</h2>
                    <ul className="flex flex-col gap-2">
                        {ongoingIncidents.map((incident) => (
                            <li key={incident.id}>
                                <PublicIncidentRow
                                    incident={incident}
                                    monitorName={monitorNameById.get(incident.monitor_id)}
                                />
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            <OverallBanner status={overallStatus} count={monitors.length} />

            {monitors.length === 0 ? (
                <div className="text-center text-secondary text-sm p-8 border rounded border-dashed">{placeholder}</div>
            ) : (
                <ul className="flex flex-col gap-2">
                    {monitors.map((monitor) => (
                        <li key={monitor.id}>
                            <PreviewMonitorRow monitor={monitor} />
                        </li>
                    ))}
                </ul>
            )}

            {recentIncidents.length > 0 && (
                <section className="flex flex-col gap-2">
                    <h2 className="text-sm font-semibold text-primary m-0">Recently resolved</h2>
                    <ul className="flex flex-col gap-2">
                        {recentIncidents.map((incident) => (
                            <li key={incident.id}>
                                <PublicIncidentRow
                                    incident={incident}
                                    monitorName={monitorNameById.get(incident.monitor_id)}
                                />
                            </li>
                        ))}
                    </ul>
                </section>
            )}
        </div>
    )
}

function PublicIncidentRow({ incident, monitorName }: { incident: Incident; monitorName?: string }): JSX.Element {
    const ongoing = incident.resolved_at === null
    return (
        <div className="flex flex-col gap-1 p-3 border rounded bg-surface-primary">
            <div className="flex items-center gap-2 min-w-0">
                <span
                    className={cn(
                        'inline-block w-2 h-2 rounded-full shrink-0',
                        ongoing ? 'bg-danger animate-pulse' : 'bg-success'
                    )}
                    aria-hidden
                />
                <span className="font-medium truncate">{incident.name}</span>
            </div>
            {incident.description && (
                <div className="text-xs text-secondary whitespace-pre-wrap">{incident.description}</div>
            )}
            {!ongoing && incident.resolution_note && (
                <div className="text-xs whitespace-pre-wrap p-2 rounded bg-surface-secondary">
                    <span className="font-semibold">Resolution: </span>
                    {incident.resolution_note}
                </div>
            )}
            <div className="flex flex-wrap gap-x-3 text-[11px] text-secondary">
                {monitorName && <span className="font-medium">{monitorName}</span>}
                <span>Started {dayjs(incident.started_at).format('MMM D, YYYY h:mm A')}</span>
                {incident.resolved_at && (
                    <span>Resolved {dayjs(incident.resolved_at).format('MMM D, YYYY h:mm A')}</span>
                )}
            </div>
        </div>
    )
}

function OverallBanner({ status, count }: { status: MonitorStatus | 'mixed' | 'empty'; count: number }): JSX.Element {
    if (status === 'empty') {
        return (
            <div className="flex items-center justify-between px-4 py-3 rounded border">
                <span className="font-medium text-secondary">No monitors selected yet</span>
            </div>
        )
    }
    const config = bannerConfig(status, count)
    return (
        <div className="flex items-center justify-between px-4 py-3 rounded border">
            <div className="flex items-center gap-2.5">
                <span className={cn('inline-block w-2.5 h-2.5 rounded-full', config.dotClass)} aria-hidden />
                <span className="font-semibold">{config.label}</span>
            </div>
        </div>
    )
}

function PreviewMonitorRow({ monitor }: { monitor: MonitorSummary }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 p-4 border rounded bg-surface-primary">
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                    <span
                        className={cn('inline-block w-2.5 h-2.5 rounded-full shrink-0', statusDotClass(monitor.status))}
                        aria-hidden
                    />
                    <span className="font-medium truncate">{monitor.name}</span>
                </div>
                <StatusTag status={monitor.status} />
            </div>
            <StatusTimeline buckets={monitor.daily_buckets} />
        </div>
    )
}

function StatusTag({ status }: { status: MonitorStatus }): JSX.Element {
    const type = status === 'up' ? 'success' : status === 'down' ? 'danger' : 'muted'
    const label = status === 'up' ? 'Operational' : status === 'down' ? 'Down' : 'No data'
    return (
        <LemonTag type={type} size="small">
            {label}
        </LemonTag>
    )
}

function StatusTimeline({ buckets }: { buckets: DailyBucket[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-px h-5">
                {buckets.map((b) => (
                    <Tooltip key={b.date} title={tooltipForBucket(b)}>
                        <div
                            className={cn(
                                'flex-1 h-full rounded-sm cursor-help transition-opacity hover:opacity-80',
                                dailyStatusClass(b.status)
                            )}
                        />
                    </Tooltip>
                ))}
            </div>
            <div className="flex justify-between text-[10px] text-secondary">
                <span>{buckets.length}d ago</span>
                <span>Today</span>
            </div>
        </div>
    )
}

function computeOverallStatus(monitors: MonitorSummary[]): MonitorStatus | 'mixed' | 'empty' {
    if (monitors.length === 0) {
        return 'empty'
    }
    const hasDown = monitors.some((m) => m.status === 'down')
    if (hasDown) {
        return 'down'
    }
    const allUp = monitors.every((m) => m.status === 'up')
    if (allUp) {
        return 'up'
    }
    const allNoData = monitors.every((m) => m.status === 'no_data')
    if (allNoData) {
        return 'no_data'
    }
    return 'mixed'
}

function bannerConfig(status: MonitorStatus | 'mixed', count: number): { label: string; dotClass: string } {
    switch (status) {
        case 'up':
            return {
                label: `All systems operational`,
                dotClass: 'bg-success',
            }
        case 'down':
            return {
                label: `Some systems are down`,
                dotClass: 'bg-danger animate-pulse',
            }
        case 'no_data':
            return {
                label: `Awaiting data from ${count} monitor${count === 1 ? '' : 's'}`,
                dotClass: 'bg-border-bold',
            }
        case 'mixed':
            return {
                label: `Partial — some monitors have no data`,
                dotClass: 'bg-warning',
            }
    }
}

function statusDotClass(status: MonitorStatus): string {
    if (status === 'up') {
        return 'bg-success'
    }
    if (status === 'down') {
        return 'bg-danger animate-pulse'
    }
    return 'bg-border-bold'
}

function dailyStatusClass(status: DailyStatus): string {
    if (status === 'up') {
        return 'bg-success'
    }
    if (status === 'down') {
        return 'bg-danger'
    }
    if (status === 'degraded') {
        return 'bg-warning'
    }
    return 'bg-border'
}

function tooltipForBucket(bucket: DailyBucket): string {
    const date = dayjs(bucket.date).format('MMM D, YYYY')
    if (bucket.status === 'no_data') {
        return `${date} — no checks`
    }
    if (bucket.status === 'up') {
        return `${date} — all ${bucket.total} checks succeeded`
    }
    if (bucket.status === 'down') {
        return `${date} — all ${bucket.total} checks failed`
    }
    return `${date} — ${bucket.failed} of ${bucket.total} checks failed`
}
