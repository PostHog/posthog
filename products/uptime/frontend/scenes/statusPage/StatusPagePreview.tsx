import { useState } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { cn } from 'lib/utils/css-classes'

import { IncidentTimeline } from '../IncidentTimeline'
import { DailyBucket, DailyStatus, Incident, MonitorStatus, MonitorSummary } from '../uptimeSceneLogic'

interface StatusPagePreviewProps {
    title: string
    monitors: MonitorSummary[]
    publishedAt?: string | null
    ongoingIncidents?: Incident[]
    recentIncidents?: Incident[]
    placeholder?: string
    isPublic?: boolean
}

export function StatusPagePreview({
    title,
    monitors,
    publishedAt,
    ongoingIncidents = [],
    recentIncidents = [],
    placeholder = 'Add monitors from the left to see them here.',
    isPublic = false,
}: StatusPagePreviewProps): JSX.Element {
    const overallStatus = computeOverallStatus(monitors)
    const monitorNameById = new Map(monitors.map((m) => [m.id, m.name]))
    const allIncidents = [...ongoingIncidents, ...recentIncidents]

    return (
        <div className="flex flex-col gap-6 w-full max-w-2xl mx-auto">
            <header className="flex flex-col gap-2">
                <h1 className="text-2xl font-semibold text-primary">{title || 'Untitled status page'}</h1>
                {publishedAt && (
                    <div className="text-xs text-secondary">Last updated {dayjs(publishedAt).fromNow()}</div>
                )}
            </header>

            {ongoingIncidents.length > 0 && (
                <section className="flex flex-col gap-2 p-4 rounded-lg border border-danger/30 bg-danger-highlight">
                    <h2 className="text-sm font-semibold text-danger m-0">
                        {isPublic ? 'Ongoing incidents' : 'Ongoing declared incidents'}
                    </h2>
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
                            <PreviewMonitorRow
                                monitor={monitor}
                                incidents={allIncidents.filter((i) => i.monitor_id === monitor.id)}
                            />
                        </li>
                    ))}
                </ul>
            )}

            {recentIncidents.length > 0 && (
                <section className="flex flex-col gap-2 p-4 rounded-lg border bg-surface-secondary">
                    <h2 className="text-sm font-semibold text-secondary m-0 uppercase tracking-wide">Past incidents</h2>
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
            {incident.updates && incident.updates.length > 0 && (
                <IncidentTimeline updates={incident.updates} limit={ongoing ? 5 : 3} className="mt-1" />
            )}
            {!ongoing && incident.resolution_note && (
                <div className="text-xs whitespace-pre-wrap p-2 rounded bg-surface-secondary">
                    <span className="font-semibold">Resolution: </span>
                    {incident.resolution_note}
                </div>
            )}
            <div className="flex flex-wrap gap-x-3 text-[11px] text-secondary">
                {monitorName && <span className="font-medium">{monitorName}</span>}
                <span>Started {dayjs(incident.started_at).fromNow()}</span>
                {incident.resolved_at && <span>Resolved {dayjs(incident.resolved_at).fromNow()}</span>}
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

function PreviewMonitorRow({ monitor, incidents }: { monitor: MonitorSummary; incidents: Incident[] }): JSX.Element {
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
            <StatusTimeline buckets={monitor.daily_buckets} incidents={incidents} />
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

function StatusTimeline({ buckets, incidents }: { buckets: DailyBucket[]; incidents: Incident[] }): JSX.Element {
    const [openDate, setOpenDate] = useState<string | null>(null)
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-px h-5">
                {buckets.map((b) => (
                    <BucketCell
                        key={b.date}
                        bucket={b}
                        incidents={incidentsForBucket(b, incidents)}
                        open={openDate === b.date}
                        onOpenChange={(open) => setOpenDate(open ? b.date : null)}
                    />
                ))}
            </div>
            <div className="flex justify-between text-[10px] text-secondary">
                <span>{buckets.length}d ago</span>
                <span>Today</span>
            </div>
        </div>
    )
}

function BucketCell({
    bucket,
    incidents,
    open,
    onOpenChange,
}: {
    bucket: DailyBucket
    incidents: Incident[]
    open: boolean
    onOpenChange: (open: boolean) => void
}): JSX.Element {
    return (
        <Popover
            visible={open}
            onClickOutside={() => onOpenChange(false)}
            placement="top"
            overlay={<BucketPopoverContent bucket={bucket} incidents={incidents} />}
        >
            <div
                role="button"
                tabIndex={0}
                onClick={() => onOpenChange(!open)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onOpenChange(!open)
                    }
                }}
                className={cn(
                    'flex-1 h-full rounded-sm cursor-pointer transition-opacity hover:opacity-80',
                    dailyStatusClass(bucket.status)
                )}
            />
        </Popover>
    )
}

function BucketPopoverContent({ bucket, incidents }: { bucket: DailyBucket; incidents: Incident[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 max-w-xs">
            <div className="text-xs font-semibold">{dayjs(bucket.date).format('MMM D, YYYY')}</div>
            <div className="text-xs text-secondary">{bucketSummary(bucket)}</div>
            {incidents.length === 0 ? (
                <div className="text-xs text-secondary">No incidents on this day.</div>
            ) : (
                <ul className="flex flex-col gap-1.5">
                    {incidents.map((incident) => {
                        const ongoing = incident.resolved_at === null
                        return (
                            <li key={incident.id} className="flex items-start gap-1.5">
                                <span
                                    className={cn(
                                        'inline-block w-1.5 h-1.5 rounded-full shrink-0 mt-1.5',
                                        ongoing ? 'bg-danger animate-pulse' : 'bg-success'
                                    )}
                                    aria-hidden
                                />
                                <div className="flex flex-col min-w-0">
                                    <span className="text-xs font-medium truncate">{incident.name}</span>
                                    <span className="text-[11px] text-secondary">
                                        {dayjs(incident.started_at).format('h:mm A')}
                                        {incident.resolved_at
                                            ? ` – ${dayjs(incident.resolved_at).format('h:mm A')}`
                                            : ' – ongoing'}
                                    </span>
                                </div>
                            </li>
                        )
                    })}
                </ul>
            )}
        </div>
    )
}

function incidentsForBucket(bucket: DailyBucket, incidents: Incident[]): Incident[] {
    const start = dayjs(bucket.date).startOf('day')
    const end = dayjs(bucket.date).endOf('day')
    return incidents.filter((incident) => {
        const incidentStart = dayjs(incident.started_at)
        const incidentEnd = incident.resolved_at ? dayjs(incident.resolved_at) : dayjs()
        return incidentStart.isBefore(end) && incidentEnd.isAfter(start)
    })
}

function bucketSummary(bucket: DailyBucket): string {
    if (bucket.status === 'no_data') {
        return 'No checks'
    }
    if (bucket.status === 'up') {
        return `All ${bucket.total} checks succeeded`
    }
    if (bucket.status === 'down') {
        return `All ${bucket.total} checks failed`
    }
    return `${bucket.failed} of ${bucket.total} checks failed`
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
