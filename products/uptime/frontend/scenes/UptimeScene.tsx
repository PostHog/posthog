import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconPencil, IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonInput, LemonModal, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import type { DailyBucketDTOApi, MonitorSummaryDTOApi } from '../generated/api.schemas'
import { OverallStats, uptimeSceneLogic } from './uptimeSceneLogic'

export const scene: SceneExport = {
    component: UptimeScene,
    logic: uptimeSceneLogic,
}

export function UptimeScene(): JSX.Element {
    const { monitorSummaries, monitorSummariesLoading, overallStats } = useValues(uptimeSceneLogic)
    const { setCreateModalOpen, loadMonitorSummaries, startEditing, confirmDeleteMonitor } =
        useActions(uptimeSceneLogic)

    const hasMonitors = monitorSummaries.length > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name="Uptime"
                description="Monitor URLs and view their recent ping history."
                resourceType={{ type: 'uptime' }}
                actions={
                    <div className="flex gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconRefresh />}
                            loading={monitorSummariesLoading}
                            data-attr="refresh-monitors"
                            tooltip="Refresh monitor data"
                            onClick={() => loadMonitorSummaries()}
                        >
                            Refresh
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            size="small"
                            data-attr="create-monitor"
                            onClick={() => setCreateModalOpen(true)}
                        >
                            Create monitor
                        </LemonButton>
                    </div>
                }
            />

            <div className="flex flex-col gap-4">
                {hasMonitors && <OverallStatusBanner stats={overallStats} />}

                {!hasMonitors && !monitorSummariesLoading ? (
                    <LemonCard hoverEffect={false} className="flex flex-col items-center gap-2 p-8 text-center">
                        <div className="text-xl font-semibold">No monitors yet</div>
                        <div className="text-secondary max-w-md">
                            Add a URL to start tracking its uptime, latency, and response codes.
                        </div>
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            onClick={() => setCreateModalOpen(true)}
                            size="small"
                        >
                            Create monitor
                        </LemonButton>
                    </LemonCard>
                ) : (
                    <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                        {monitorSummariesLoading && !hasMonitors
                            ? Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} />)
                            : monitorSummaries.map((monitor) => (
                                  <MonitorTile
                                      key={monitor.id}
                                      monitor={monitor}
                                      onEdit={() => startEditing(monitor)}
                                      onDelete={() => confirmDeleteMonitor({ id: monitor.id, name: monitor.name })}
                                  />
                              ))}
                    </div>
                )}
            </div>

            <CreateMonitorModal />
            <EditMonitorModal />
        </SceneContent>
    )
}

function OverallStatusBanner({ stats }: { stats: OverallStats }): JSX.Element {
    const { total, operational, down, noData, avgUptime, avgLatencyMs } = stats
    const allUp = down === 0 && operational === total - noData && total > 0
    const someDown = down > 0

    const banner = someDown
        ? { label: `${down} of ${total} monitors down`, tone: 'danger' as const }
        : allUp
          ? { label: `All systems operational — ${operational} of ${total} up`, tone: 'success' as const }
          : { label: `Awaiting data — ${noData} of ${total} monitors`, tone: 'muted' as const }

    return (
        <div className="flex flex-col gap-2 p-4 border rounded bg-surface-primary">
            <div className="flex items-center gap-2">
                <StatusDot status={someDown ? 'down' : allUp ? 'up' : 'no_data'} size="lg" />
                <span className={cn('font-semibold text-base', toneToTextClass(banner.tone))}>{banner.label}</span>
            </div>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm text-secondary">
                <Stat label="Monitors" value={String(total)} />
                <Stat
                    label="Uptime (90d)"
                    value={avgUptime !== null ? formatPercent(avgUptime) : '—'}
                    hint="Successful checks ÷ total checks across all monitors"
                />
                <Stat label="Avg latency (24h)" value={avgLatencyMs !== null ? `${avgLatencyMs} ms` : '—'} />
            </div>
        </div>
    )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }): JSX.Element {
    const content = (
        <div className="flex items-baseline gap-1.5">
            <span className="text-secondary">{label}</span>
            <span className="font-medium text-primary">{value}</span>
        </div>
    )
    return hint ? <Tooltip title={hint}>{content}</Tooltip> : content
}

function MonitorTile({
    monitor,
    onEdit,
    onDelete,
}: {
    monitor: MonitorSummaryDTOApi
    onEdit: () => void
    onDelete: () => void
}): JSX.Element {
    // Interactive children stopPropagation so clicking them doesn't also fire the
    // tile-wide navigation.
    const stop = (e: React.MouseEvent): void => e.stopPropagation()

    return (
        <LemonCard
            hoverEffect
            onClick={() => router.actions.push(urls.uptimeMonitor(monitor.id))}
            className="flex flex-col gap-3 p-4"
        >
            <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <StatusDot status={monitor.status} />
                    <div className="min-w-0 flex flex-col">
                        <div className="font-semibold truncate" title={monitor.name}>
                            {monitor.name}
                        </div>
                        <Link
                            to={monitor.url}
                            target="_blank"
                            onClick={stop}
                            className="text-xs text-secondary truncate"
                            title={monitor.url}
                        >
                            {monitor.url}
                        </Link>
                    </div>
                </div>
                <div className="flex items-center gap-1 shrink-0" onClick={stop}>
                    <LemonButton size="xsmall" icon={<IconPencil />} aria-label="Edit monitor" onClick={onEdit} />
                    <LemonButton
                        size="xsmall"
                        status="danger"
                        icon={<IconTrash />}
                        aria-label="Delete monitor"
                        onClick={onDelete}
                    />
                </div>
            </div>

            <div className="flex items-baseline justify-between gap-2">
                <div className="flex flex-col">
                    <span className="text-2xl font-semibold">
                        {monitor.uptime_90d != null ? formatPercent(monitor.uptime_90d) : '—'}
                    </span>
                    <span className="text-xs text-secondary">90d uptime</span>
                </div>
                <div className="flex flex-col items-end">
                    <span className="text-sm font-medium">
                        {monitor.avg_latency_24h_ms != null ? `${monitor.avg_latency_24h_ms} ms` : '—'}
                    </span>
                    <span className="text-xs text-secondary">avg 24h</span>
                </div>
            </div>

            <StatusTimeline buckets={monitor.daily_buckets} />

            <div className="text-xs text-secondary">
                {monitor.last_ping_at ? `Last checked ${dayjs(monitor.last_ping_at).fromNow()}` : 'No checks yet'}
            </div>
        </LemonCard>
    )
}

export function StatusTimeline({ buckets }: { buckets: DailyBucketDTOApi[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-px h-6">
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

export function StatusDot({
    status,
    size = 'md',
}: {
    status: MonitorSummaryDTOApi['status']
    size?: 'md' | 'lg'
}): JSX.Element {
    const dimensions = size === 'lg' ? 'w-3 h-3' : 'w-2.5 h-2.5'
    const colorClass = status === 'up' ? 'bg-success' : status === 'down' ? 'bg-danger' : 'bg-border-bold'
    return (
        <span
            className={cn('inline-block rounded-full shrink-0', dimensions, colorClass, {
                'animate-pulse': status === 'down',
            })}
            aria-label={statusLabel(status)}
        />
    )
}

function SkeletonCard(): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            <div className="h-4 bg-border rounded w-3/4" />
            <div className="h-3 bg-border rounded w-1/2" />
            <div className="h-6 bg-border rounded w-2/3 mt-2" />
            <div className="h-6 bg-border rounded" />
        </LemonCard>
    )
}

function CreateMonitorModal(): JSX.Element {
    const { createModalOpen, isCreateMonitorSubmitting } = useValues(uptimeSceneLogic)
    const { setCreateMonitorValue, submitCreateMonitor, setCreateModalOpen } = useActions(uptimeSceneLogic)

    return (
        <LemonModal
            isOpen={createModalOpen}
            onClose={() => setCreateModalOpen(false)}
            title="Create monitor"
            description="PostHog pings the URL every 5 minutes and computes uptime and latency from the checks."
            footer={
                <LemonButton type="primary" loading={isCreateMonitorSubmitting} onClick={() => submitCreateMonitor()}>
                    Create monitor
                </LemonButton>
            }
        >
            <Form logic={uptimeSceneLogic} formKey="createMonitor" className="deprecated-space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="My website" onChange={(v) => setCreateMonitorValue('name', v)} />
                </LemonField>
                <LemonField name="url" label="URL">
                    <LemonInput placeholder="https://example.com" onChange={(v) => setCreateMonitorValue('url', v)} />
                </LemonField>
            </Form>
        </LemonModal>
    )
}

function EditMonitorModal(): JSX.Element {
    const { editingMonitorId, isEditMonitorSubmitting } = useValues(uptimeSceneLogic)
    const { setEditMonitorValue, submitEditMonitor, stopEditing } = useActions(uptimeSceneLogic)

    return (
        <LemonModal
            isOpen={editingMonitorId !== null}
            onClose={stopEditing}
            title="Edit monitor"
            footer={
                <LemonButton type="primary" loading={isEditMonitorSubmitting} onClick={() => submitEditMonitor()}>
                    Save
                </LemonButton>
            }
        >
            <Form logic={uptimeSceneLogic} formKey="editMonitor" className="deprecated-space-y-4">
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

function statusLabel(status: MonitorSummaryDTOApi['status']): string {
    switch (status) {
        case 'up':
            return 'Operational'
        case 'down':
            return 'Down'
        default:
            return 'No data'
    }
}

export function dailyStatusToBgClass(status: DailyBucketDTOApi['status']): string {
    switch (status) {
        case 'up':
            return 'bg-success'
        case 'degraded':
            return 'bg-warning'
        case 'down':
            return 'bg-danger'
        default:
            return 'bg-border'
    }
}

export function bucketTooltipText(bucket: DailyBucketDTOApi): string {
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

export function formatPercent(value: number): string {
    if (value >= 1) {
        return '100%'
    }
    return `${(value * 100).toFixed(2)}%`
}

export function toneToTextClass(tone: 'success' | 'danger' | 'muted'): string {
    switch (tone) {
        case 'success':
            return 'text-success'
        case 'danger':
            return 'text-danger'
        case 'muted':
            return 'text-secondary'
    }
}
