import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconArrowLeft, IconPencil, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonModal,
    LemonSkeleton,
    LemonTable,
    LemonTag,
    Link,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { OutageDTOApi, PingDTOApi } from '../generated/api.schemas'
import { uptimeMonitorSceneLogic } from './uptimeMonitorSceneLogic'
import { StatusDot, StatusTimeline, formatPercent, toneToTextClass } from './UptimeScene'

export const scene: SceneExport = {
    component: UptimeMonitorScene,
    logic: uptimeMonitorSceneLogic,
}

export function UptimeMonitorScene(): JSX.Element {
    const { summary, summaryLoading, pings, pingsLoading, outages, outagesLoading } = useValues(uptimeMonitorSceneLogic)
    const { setEditModalOpen, confirmDeleteMonitor } = useActions(uptimeMonitorSceneLogic)

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

    return (
        <SceneContent>
            {/* No description prop — kills both the URL subtitle and the collapse toggle
                that auto-renders next to descriptions. The URL is still visible inside the
                status banner below. */}
            <SceneTitleSection
                name={summary.name}
                resourceType={{ type: 'uptime' }}
                actions={
                    <div className="flex gap-2">
                        <LemonButton type="secondary" icon={<IconPencil />} onClick={() => setEditModalOpen(true)}>
                            Edit
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() => confirmDeleteMonitor()}
                        >
                            Delete
                        </LemonButton>
                    </div>
                }
            />

            <EditMonitorModal />

            <div className="flex flex-col gap-2 p-4 border rounded bg-surface-primary">
                <div className="flex items-center gap-2 flex-wrap">
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
                        value={summary.uptime_90d != null ? formatPercent(summary.uptime_90d) : '—'}
                    />
                    <Metric
                        label="Avg latency (24h)"
                        value={summary.avg_latency_24h_ms != null ? `${summary.avg_latency_24h_ms} ms` : '—'}
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
                <div className="flex items-baseline gap-3">
                    <div className="font-semibold">90-day uptime history</div>
                    <div className="text-xs text-secondary">
                        {summary.daily_buckets.filter((b) => b.status === 'up').length} of{' '}
                        {summary.daily_buckets.length} days clean
                    </div>
                </div>
                <StatusTimeline buckets={summary.daily_buckets} />
            </LemonCard>

            <div className="grid gap-4 lg:grid-cols-2">
                <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
                    <div className="font-semibold">Recent pings</div>
                    <LemonTable
                        loading={pingsLoading}
                        dataSource={pings}
                        columns={[
                            {
                                title: 'When',
                                dataIndex: 'timestamp',
                                render: (_, row: PingDTOApi) => dayjs(row.timestamp).fromNow(),
                            },
                            {
                                title: 'Outcome',
                                dataIndex: 'outcome',
                                render: (_, row: PingDTOApi) => (
                                    <LemonTag type={row.outcome === 'success' ? 'success' : 'danger'}>
                                        {row.outcome}
                                    </LemonTag>
                                ),
                            },
                            {
                                title: 'Status',
                                dataIndex: 'status_code',
                                render: (_, row: PingDTOApi) => (row.status_code ? String(row.status_code) : '—'),
                            },
                            {
                                title: 'Latency',
                                dataIndex: 'latency_ms',
                                render: (_, row: PingDTOApi) => `${row.latency_ms} ms`,
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
                    <OutagesList outages={outages} loading={outagesLoading} />
                </LemonCard>
            </div>
        </SceneContent>
    )
}

function OutagesList({ outages, loading }: { outages: OutageDTOApi[]; loading: boolean }): JSX.Element {
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
                <OutageTile key={`${outage.started_at}-${outage.resolved_at ?? 'ongoing'}`} outage={outage} />
            ))}
        </div>
    )
}

function OutageTile({ outage }: { outage: OutageDTOApi }): JSX.Element {
    const ongoing = !outage.resolved_at
    const end = outage.resolved_at ? dayjs(outage.resolved_at) : dayjs()
    const durationLabel = formatDuration(dayjs(outage.started_at), end)

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
        </LemonCard>
    )
}

function EditMonitorModal(): JSX.Element {
    const { editModalOpen, isEditMonitorSubmitting } = useValues(uptimeMonitorSceneLogic)
    const { setEditMonitorValue, submitEditMonitor, setEditModalOpen } = useActions(uptimeMonitorSceneLogic)

    return (
        <LemonModal
            isOpen={editModalOpen}
            onClose={() => setEditModalOpen(false)}
            title="Edit monitor"
            footer={
                <LemonButton type="primary" loading={isEditMonitorSubmitting} onClick={() => submitEditMonitor()}>
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
