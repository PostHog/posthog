import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconArrowLeft, IconGraph, IconPencil, IconPlay, IconPlus, IconTrash, IconWarning } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonModal,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { IncidentTile } from './IncidentTile'
import { uptimeMonitorSceneLogic } from './uptimeMonitorSceneLogic'
import { DailyBucket, DailyStatus, Incident, MonitorStatus, Outage, Ping } from './uptimeSceneLogic'

export const scene: SceneExport = {
    component: UptimeMonitorScene,
    logic: uptimeMonitorSceneLogic,
}

export function UptimeMonitorScene(): JSX.Element {
    const { summary, summaryLoading, pings, pingsLoading, incidents, incidentsLoading, outages, outagesLoading } =
        useValues(uptimeMonitorSceneLogic)
    const {
        pingNow,
        setEditModalOpen,
        deleteMonitor,
        openCreateIncident,
        declareIncidentFromOutage,
        startEditingIncident,
        promptResolveIncident,
        reopenIncident,
        confirmDeleteIncident,
    } = useActions(uptimeMonitorSceneLogic)

    if (summaryLoading && !summary) {
        return (
            <SceneContent>
                <DetailSkeleton />
            </SceneContent>
        )
    }

    if (!summary) {
        return (
            <SceneContent>
                <LemonCard hoverEffect={false} className="flex flex-col items-center gap-2 p-8 text-center">
                    <div className="text-xl font-semibold">Monitor not found</div>
                    <div className="text-secondary">It may have been deleted.</div>
                    <LemonButton type="primary" to={urls.uptime()} icon={<IconArrowLeft />}>
                        Back to monitors
                    </LemonButton>
                </LemonCard>
            </SceneContent>
        )
    }

    const tone = summary.status === 'up' ? 'success' : summary.status === 'down' ? 'danger' : 'muted'

    const onDelete = (): void => {
        LemonDialog.open({
            title: `Delete monitor "${summary.name}"?`,
            description: 'Historical pings stay in the audit log; the monitor card disappears from the list.',
            primaryButton: {
                children: 'Delete monitor',
                status: 'danger',
                onClick: deleteMonitor,
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <SceneContent>
            {/* No description prop — kills both the URL subtitle and the collapse toggle
                that auto-renders next to descriptions. The URL is still visible inside the
                status banner below. */}
            <SceneTitleSection
                name={summary.name}
                resourceType={{ type: 'default_icon_type' }}
                actions={
                    <div className="flex gap-2">
                        <LemonButton type="secondary" icon={<IconPencil />} onClick={() => setEditModalOpen(true)}>
                            Edit
                        </LemonButton>
                        <LemonButton type="secondary" status="danger" icon={<IconTrash />} onClick={onDelete}>
                            Delete
                        </LemonButton>
                        <LemonButton type="primary" icon={<IconPlay />} onClick={pingNow}>
                            Ping now
                        </LemonButton>
                    </div>
                }
            />

            <EditMonitorModal />

            <div className="flex flex-col gap-2 p-4 border rounded bg-surface-primary">
                <div className="flex items-center gap-2">
                    <StatusDot status={summary.status} size="lg" />
                    <span className={cn('font-semibold text-base', toneToTextClass(tone))}>
                        {summary.status === 'up' ? 'Operational' : summary.status === 'down' ? 'Down' : 'Awaiting data'}
                    </span>
                    <LemonTag type={tone} size="small">
                        {summary.last_ping_at
                            ? `Last checked ${dayjs(summary.last_ping_at).fromNow()}`
                            : 'No checks yet'}
                    </LemonTag>
                </div>
                <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2 mt-2">
                    <Metric
                        label="90d uptime"
                        value={summary.uptime_90d !== null ? formatPercent(summary.uptime_90d) : '—'}
                    />
                    <Metric
                        label="Avg latency (24h)"
                        value={summary.avg_latency_24h_ms !== null ? `${summary.avg_latency_24h_ms} ms` : '—'}
                    />
                    <Metric
                        label="URL"
                        value={
                            <Link to={summary.url} target="_blank" className="text-base font-medium">
                                {summary.url}
                            </Link>
                        }
                    />
                </div>
            </div>

            <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-baseline gap-3">
                        <div className="font-semibold">30-day uptime history</div>
                        <div className="text-xs text-secondary">
                            {summary.daily_buckets.filter((b) => b.status === 'up').length} of{' '}
                            {summary.daily_buckets.length} days clean
                        </div>
                    </div>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconGraph />}
                        to={buildUptimeInsightUrl(summary.id)}
                        tooltip="Open daily uptime % as an editable SQL insight"
                    >
                        Open as insight
                    </LemonButton>
                </div>
                <StatusTimeline buckets={summary.daily_buckets} />
            </LemonCard>

            <div className="grid gap-4 lg:grid-cols-3">
                <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
                    <div className="font-semibold">Recent pings</div>
                    <LemonTable
                        loading={pingsLoading}
                        dataSource={pings}
                        columns={[
                            {
                                title: 'When',
                                dataIndex: 'timestamp',
                                render: (_, row: Ping) => dayjs(row.timestamp).fromNow(),
                            },
                            {
                                title: 'Outcome',
                                dataIndex: 'outcome',
                                render: (_, row: Ping) => (
                                    <LemonTag type={row.outcome === 'success' ? 'success' : 'danger'}>
                                        {row.outcome}
                                    </LemonTag>
                                ),
                            },
                            {
                                title: 'Status',
                                dataIndex: 'status_code',
                                render: (_, row: Ping) => (row.status_code ? String(row.status_code) : '—'),
                            },
                            {
                                title: 'Latency',
                                dataIndex: 'latency_ms',
                                render: (_, row: Ping) => `${row.latency_ms} ms`,
                            },
                        ]}
                        emptyState="No pings recorded yet."
                    />
                </LemonCard>
                <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
                    <div className="flex items-center justify-between">
                        <div className="font-semibold">Outages</div>
                        <span className="text-xs text-secondary">Last 7 days</span>
                    </div>
                    <OutagesList
                        outages={outages}
                        loading={outagesLoading}
                        monitorUrl={summary.url}
                        onDeclare={declareIncidentFromOutage}
                    />
                </LemonCard>
                <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
                    <div className="flex items-center justify-between">
                        <div className="font-semibold">Declared incidents</div>
                        {incidents.length > 0 && (
                            <LemonButton type="primary" size="small" icon={<IconPlus />} onClick={openCreateIncident}>
                                Declare new
                            </LemonButton>
                        )}
                    </div>
                    <IncidentsList
                        incidents={incidents}
                        loading={incidentsLoading}
                        onCreate={openCreateIncident}
                        onEdit={startEditingIncident}
                        onResolve={promptResolveIncident}
                        onReopen={(id) => reopenIncident(id)}
                        onDelete={(incident) => confirmDeleteIncident({ id: incident.id, name: incident.name })}
                    />
                </LemonCard>
            </div>
            <IncidentModal />
        </SceneContent>
    )
}

function OutagesList({
    outages,
    loading,
    monitorUrl,
    onDeclare,
}: {
    outages: Outage[]
    loading: boolean
    monitorUrl: string
    onDeclare: (outage: Outage) => void
}): JSX.Element {
    if (loading && outages.length === 0) {
        return <LemonSkeleton className="h-24 w-full" />
    }

    if (outages.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center gap-2 py-12 text-center">
                <div className="text-sm text-secondary max-w-xs">
                    No outages detected in the last 7 days. All clear.
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            {outages.map((outage) => (
                <OutageTile
                    key={`${outage.started_at}-${outage.resolved_at ?? 'ongoing'}`}
                    outage={outage}
                    monitorUrl={monitorUrl}
                    onDeclare={() => onDeclare(outage)}
                />
            ))}
        </div>
    )
}

function OutageTile({
    outage,
    monitorUrl,
    onDeclare,
}: {
    outage: Outage
    monitorUrl: string
    onDeclare: () => void
}): JSX.Element {
    const ongoing = outage.resolved_at === null
    const end = outage.resolved_at ? dayjs(outage.resolved_at) : dayjs()
    const durationLabel = formatDuration(dayjs(outage.started_at), end)
    const host = hostFromUrl(monitorUrl)
    const dateRange = buildOutageDateRange(outage)
    const logsUrl = `${urls.logs()}?dateRange=${encodeURIComponent(JSON.stringify(dateRange))}${
        host ? `&searchTerm=${encodeURIComponent(host)}` : ''
    }`
    const errorsUrl = urls.errorTracking({ dateRange })

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-2 p-3">
            <div className="flex items-center justify-between gap-2 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <span
                        className={cn(
                            'inline-block w-2.5 h-2.5 rounded-full shrink-0',
                            ongoing ? 'bg-danger animate-pulse' : 'bg-success'
                        )}
                        aria-hidden
                    />
                    <div className="font-semibold truncate">
                        {ongoing ? `Ongoing · ${durationLabel}` : durationLabel}
                    </div>
                </div>
                <span className="text-[11px] text-secondary shrink-0">
                    {outage.fail_count} failed{outage.last_status_code ? ` · ${outage.last_status_code}` : ''}
                </span>
            </div>
            <div className="text-[11px] text-secondary">
                Started {dayjs(outage.started_at).fromNow()}
                {outage.resolved_at && ` · resolved ${dayjs(outage.resolved_at).fromNow()}`}
            </div>
            <div className="flex flex-wrap gap-1 mt-1">
                <LemonButton size="xsmall" type="secondary" to={logsUrl} targetBlank>
                    Logs
                </LemonButton>
                <LemonButton size="xsmall" type="secondary" to={errorsUrl} targetBlank icon={<IconWarning />}>
                    Issues
                </LemonButton>
                <LemonButton size="xsmall" type="primary" onClick={onDeclare}>
                    Declare incident
                </LemonButton>
            </div>
        </LemonCard>
    )
}

function IncidentsList({
    incidents,
    loading,
    onCreate,
    onEdit,
    onResolve,
    onReopen,
    onDelete,
}: {
    incidents: Incident[]
    loading: boolean
    onCreate: () => void
    onEdit: (incident: Incident) => void
    onResolve: (incident: Incident) => void
    onReopen: (incidentId: string) => void
    onDelete: (incident: Incident) => void
}): JSX.Element {
    if (loading && incidents.length === 0) {
        return <LemonSkeleton className="h-24 w-full" />
    }

    if (incidents.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
                <div className="text-sm text-secondary max-w-xs">No declared incidents for this monitor yet.</div>
                <LemonButton type="primary" icon={<IconPlus />} onClick={onCreate}>
                    Declare new
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3">
            {incidents.map((incident) => (
                <IncidentTile
                    key={incident.id}
                    incident={incident}
                    onEdit={() => onEdit(incident)}
                    onResolve={() => onResolve(incident)}
                    onReopen={() => onReopen(incident.id)}
                    onDelete={() => onDelete(incident)}
                />
            ))}
        </div>
    )
}

function IncidentModal(): JSX.Element {
    const { incidentModalState, isIncidentFormSubmitting, editingIncident, outagePrefill } =
        useValues(uptimeMonitorSceneLogic)
    const { setIncidentFormValue, submitIncidentForm, closeIncidentModal } = useActions(uptimeMonitorSceneLogic)

    const isCreate = incidentModalState === 'new'
    const isResolvedPrefill = isCreate && outagePrefill?.resolved_at != null
    const isOngoingPrefill = isCreate && outagePrefill !== null && outagePrefill.resolved_at === null
    const showResolutionField = isResolvedPrefill || (!isCreate && editingIncident?.resolved_at != null)
    const title = isCreate
        ? outagePrefill
            ? isResolvedPrefill
                ? 'Declare resolved incident from outage'
                : 'Declare ongoing incident from outage'
            : 'Declare incident'
        : 'Edit declared incident'

    return (
        <LemonModal
            isOpen={incidentModalState !== null}
            onClose={closeIncidentModal}
            title={title}
            footer={
                <LemonButton type="primary" loading={isIncidentFormSubmitting} onClick={() => submitIncidentForm()}>
                    {isCreate ? 'Create' : 'Save'}
                </LemonButton>
            }
        >
            <Form logic={uptimeMonitorSceneLogic} formKey="incidentForm" className="deprecated-space-y-4">
                {outagePrefill && (
                    <div className="flex flex-col gap-1 p-3 rounded bg-surface-secondary text-xs">
                        <div>
                            <span className="font-semibold">Started:</span>{' '}
                            {dayjs(outagePrefill.started_at).format('MMM D, YYYY HH:mm:ss')}
                        </div>
                        {outagePrefill.resolved_at ? (
                            <div>
                                <span className="font-semibold">Resolved:</span>{' '}
                                {dayjs(outagePrefill.resolved_at).format('MMM D, YYYY HH:mm:ss')}
                            </div>
                        ) : (
                            <div className="text-danger">Still ongoing</div>
                        )}
                    </div>
                )}
                <LemonField name="name" label="Name">
                    <LemonInput
                        placeholder={isOngoingPrefill ? 'Ongoing outage' : 'API outage'}
                        onChange={(v) => setIncidentFormValue('name', v)}
                    />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea
                        placeholder="What's happening?"
                        rows={4}
                        onChange={(v) => setIncidentFormValue('description', v)}
                    />
                </LemonField>
                {showResolutionField && (
                    <LemonField name="resolution_note" label="Resolution">
                        <LemonTextArea
                            placeholder="What fixed it?"
                            rows={3}
                            onChange={(v) => setIncidentFormValue('resolution_note', v)}
                        />
                    </LemonField>
                )}
            </Form>
        </LemonModal>
    )
}

function EditMonitorModal(): JSX.Element {
    const { editModalOpen, isEditMonitorFormSubmitting } = useValues(uptimeMonitorSceneLogic)
    const { setEditMonitorValue, submitEditMonitor, setEditModalOpen } = useActions(uptimeMonitorSceneLogic)

    return (
        <LemonModal
            isOpen={editModalOpen}
            onClose={() => setEditModalOpen(false)}
            title="Edit monitor"
            footer={
                <LemonButton type="primary" loading={isEditMonitorFormSubmitting} onClick={() => submitEditMonitor()}>
                    Save
                </LemonButton>
            }
        >
            <Form logic={uptimeMonitorSceneLogic} formKey="editMonitor" className="deprecated-space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="My website" onChange={(v) => setEditMonitorValue('name', v)} />
                </LemonField>
                <LemonField name="url" label="URL">
                    <LemonInput placeholder="https://example.com" onChange={(v) => setEditMonitorValue('url', v)} />
                </LemonField>
            </Form>
        </LemonModal>
    )
}

function Metric({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <span className="text-xs text-secondary">{label}</span>
            <span className="text-xl font-semibold">{value}</span>
        </div>
    )
}

function StatusTimeline({ buckets }: { buckets: DailyBucket[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-px h-8">
                {buckets.map((b) => (
                    <Tooltip key={b.date} title={bucketTooltipText(b)}>
                        <div
                            className={cn(
                                'flex-1 h-full rounded-sm transition-opacity hover:opacity-80',
                                dailyStatusToBgClass(b.status)
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

function StatusDot({ status, size = 'md' }: { status: MonitorStatus; size?: 'md' | 'lg' }): JSX.Element {
    const dimensions = size === 'lg' ? 'w-3 h-3' : 'w-2.5 h-2.5'
    const colorClass = status === 'up' ? 'bg-success' : status === 'down' ? 'bg-danger' : 'bg-border-bold'
    return (
        <span
            className={cn('inline-block rounded-full shrink-0', dimensions, colorClass, {
                'animate-pulse': status === 'down',
            })}
        />
    )
}

function DetailSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <LemonSkeleton className="h-8 w-64" />
            <LemonSkeleton className="h-24 w-full" />
            <LemonSkeleton className="h-24 w-full" />
            <LemonSkeleton className="h-48 w-full" />
        </div>
    )
}

function dailyStatusToBgClass(status: DailyStatus): string {
    switch (status) {
        case 'up':
            return 'bg-success'
        case 'degraded':
            return 'bg-warning'
        case 'down':
            return 'bg-danger'
        case 'no_data':
            return 'bg-border'
    }
}

function bucketTooltipText(bucket: DailyBucket): string {
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

function formatPercent(value: number): string {
    if (value >= 1) {
        return '100%'
    }
    return `${(value * 100).toFixed(2)}%`
}

function buildUptimeInsightUrl(monitorId: string): string {
    const query = `SELECT
    toDate(timestamp) AS day,
    round(100 * countIf(outcome = 'success') / count(), 2) AS uptime_pct
FROM posthog.uptime_pings
WHERE monitor_id = toUUID('${monitorId}')
    AND timestamp >= now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day`
    return urls.sqlEditor({ query })
}

function toneToTextClass(tone: 'success' | 'danger' | 'muted'): string {
    switch (tone) {
        case 'success':
            return 'text-success'
        case 'danger':
            return 'text-danger'
        case 'muted':
            return 'text-secondary'
    }
}

function formatDuration(start: dayjs.Dayjs, end: dayjs.Dayjs): string {
    const seconds = Math.max(1, end.diff(start, 'second'))
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = Math.floor(seconds / 60)
    const remainder = seconds % 60
    if (minutes < 60) {
        return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`
    }
    const hours = Math.floor(minutes / 60)
    const rmin = minutes % 60
    if (hours < 24) {
        return rmin ? `${hours}h ${rmin}m` : `${hours}h`
    }
    const days = Math.floor(hours / 24)
    const rhr = hours % 24
    return rhr ? `${days}d ${rhr}h` : `${days}d`
}

function hostFromUrl(url: string): string | null {
    try {
        return new URL(url).hostname
    } catch {
        return null
    }
}

function buildOutageDateRange(outage: Outage): { date_from: string; date_to: string } {
    // Pad each side by 5 minutes so the related logs/issues window catches the trigger and recovery.
    const pad = 5 * 60 * 1000
    const start = new Date(new Date(outage.started_at).getTime() - pad).toISOString()
    const end = new Date((outage.resolved_at ? new Date(outage.resolved_at).getTime() : Date.now()) + pad).toISOString()
    return { date_from: start, date_to: end }
}
