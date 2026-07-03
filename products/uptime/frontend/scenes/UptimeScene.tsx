import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconEllipsis, IconPencil, IconPlus, IconPulse, IconRefresh, IconTrash } from '@posthog/icons'
import {
    Button,
    Card,
    CardAction,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Dot,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DeleteMonitorDialog } from '../components/DeleteMonitorDialog'
import { formatPercent, monitorStatusDotVariant } from '../components/monitorDisplay'
import { MonitorFormFields } from '../components/MonitorFormFields'
import { StatusTimeline } from '../components/StatusTimeline'
import type { MonitorSummaryDTOApi } from '../generated/api.schemas'
import { OverallStats, uptimeSceneLogic } from './uptimeSceneLogic'

export const scene: SceneExport = {
    component: UptimeScene,
    logic: uptimeSceneLogic,
}

export function UptimeScene(): JSX.Element {
    const { monitorSummaries, monitorSummariesLoading, overallStats, monitorPendingDelete, monitorDeleting } =
        useValues(uptimeSceneLogic)
    const {
        setCreateModalOpen,
        loadMonitorSummaries,
        startEditing,
        confirmDeleteMonitor,
        cancelDeleteMonitor,
        deleteMonitor,
    } = useActions(uptimeSceneLogic)

    const hasMonitors = monitorSummaries.length > 0

    return (
        <SceneContent>
            <SceneTitleSection
                name="Uptime"
                description="Monitor URLs and view their recent ping history."
                resourceType={{ type: 'uptime' }}
                actions={
                    <div className="flex gap-2 self-center" data-quill>
                        <Button
                            variant="outline"
                            loading={monitorSummariesLoading}
                            data-attr="refresh-monitors"
                            onClick={() => loadMonitorSummaries()}
                        >
                            <IconRefresh />
                            Refresh
                        </Button>
                        <Button variant="primary" data-attr="create-monitor" onClick={() => setCreateModalOpen(true)}>
                            Create monitor
                        </Button>
                    </div>
                }
            />

            <div className="flex flex-col gap-4" data-quill>
                {hasMonitors && <OverallStatusBanner stats={overallStats} />}

                {!hasMonitors && !monitorSummariesLoading ? (
                    <Card>
                        <CardContent>
                            <Empty>
                                <EmptyHeader>
                                    <EmptyMedia variant="icon">
                                        <IconPulse />
                                    </EmptyMedia>
                                    <EmptyTitle>No monitors yet</EmptyTitle>
                                    <EmptyDescription>
                                        Add a URL to start tracking its uptime, latency, and response codes.
                                    </EmptyDescription>
                                </EmptyHeader>
                                <EmptyContent>
                                    <Button variant="primary" onClick={() => setCreateModalOpen(true)}>
                                        <IconPlus />
                                        Create monitor
                                    </Button>
                                </EmptyContent>
                            </Empty>
                        </CardContent>
                    </Card>
                ) : (
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
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
            <DeleteMonitorDialog
                monitorName={monitorPendingDelete?.name ?? null}
                deleting={monitorDeleting}
                onConfirm={() => monitorPendingDelete && deleteMonitor(monitorPendingDelete.id)}
                onCancel={cancelDeleteMonitor}
            />
        </SceneContent>
    )
}

function OverallStatusBanner({ stats }: { stats: OverallStats }): JSX.Element {
    const { total, operational, down, noData, avgUptime, avgLatencyMs } = stats
    const allUp = down === 0 && operational === total - noData && total > 0
    const someDown = down > 0

    const status = someDown ? 'down' : allUp ? 'up' : 'no_data'
    const headline = someDown
        ? `${down} of ${total} monitors down`
        : allUp
          ? `All systems operational — ${operational} of ${total} up`
          : `Awaiting data — ${noData} of ${total} monitors`

    return (
        <Card size="sm">
            <CardContent className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
                <div className="flex items-center gap-2">
                    <Dot variant={monitorStatusDotVariant(status)} pulse={someDown} />
                    <Text size="sm" weight="semibold" variant={someDown ? 'destructive' : 'default'} render={<span />}>
                        {headline}
                    </Text>
                </div>
                <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
                    <Stat label="Monitors" value={String(total)} />
                    <Stat
                        label="Uptime (90d)"
                        value={avgUptime !== null ? formatPercent(avgUptime) : '—'}
                        hint="Successful checks ÷ total checks across all monitors"
                    />
                    <Stat label="Avg latency (24h)" value={avgLatencyMs !== null ? `${avgLatencyMs} ms` : '—'} />
                </div>
            </CardContent>
        </Card>
    )
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }): JSX.Element {
    const content = (
        <>
            <Text size="xs" variant="muted" render={<span />}>
                {label}
            </Text>
            <Text size="xs" weight="medium" render={<span />}>
                {value}
            </Text>
        </>
    )
    if (!hint) {
        return <div className="flex items-baseline gap-1.5">{content}</div>
    }
    return (
        <Tooltip>
            <TooltipTrigger render={<div className="flex items-baseline gap-1.5" />}>{content}</TooltipTrigger>
            <TooltipContent>{hint}</TooltipContent>
        </Tooltip>
    )
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
        <Card
            size="sm"
            className="cursor-pointer transition-colors hover:[--card:var(--muted)]"
            onClick={() => router.actions.push(urls.uptimeMonitor(monitor.id))}
        >
            <CardHeader>
                <CardTitle className="flex min-w-0 items-center gap-2">
                    <Dot variant={monitorStatusDotVariant(monitor.status)} pulse={monitor.status === 'down'} />
                    <span className="truncate" title={monitor.name}>
                        {monitor.name}
                    </span>
                </CardTitle>
                <CardDescription className="truncate">
                    <Link
                        to={monitor.url}
                        target="_blank"
                        onClick={stop}
                        title={monitor.url}
                        className="hover:underline"
                    >
                        {monitor.url}
                    </Link>
                </CardDescription>
                <CardAction onClick={stop}>
                    <DropdownMenu>
                        <DropdownMenuTrigger render={<Button size="icon-sm" aria-label="Monitor actions" />}>
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={onEdit}>
                                <IconPencil />
                                Edit
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem variant="destructive" onClick={onDelete}>
                                <IconTrash />
                                Delete
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                <div className="flex items-baseline justify-between gap-2">
                    <div className="flex flex-col">
                        <span className="text-2xl font-semibold">
                            {monitor.uptime_90d != null ? formatPercent(monitor.uptime_90d) : '—'}
                        </span>
                        <Text size="xs" variant="muted" render={<span />}>
                            90d uptime
                        </Text>
                    </div>
                    <div className="flex flex-col items-end">
                        <Text size="sm" weight="medium" render={<span />}>
                            {monitor.avg_latency_24h_ms != null ? `${monitor.avg_latency_24h_ms} ms` : '—'}
                        </Text>
                        <Text size="xs" variant="muted" render={<span />}>
                            avg 24h
                        </Text>
                    </div>
                </div>

                <StatusTimeline buckets={monitor.daily_buckets} />

                <Text size="xs" variant="muted" render={<span />}>
                    {monitor.last_ping_at ? `Last checked ${dayjs(monitor.last_ping_at).fromNow()}` : 'No checks yet'}
                </Text>
            </CardContent>
        </Card>
    )
}

function SkeletonCard(): JSX.Element {
    return (
        <Card size="sm">
            <CardContent className="flex flex-col gap-3">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-3 w-1/2" />
                <Skeleton className="h-7 w-2/3" />
                <Skeleton className="h-6 w-full" />
            </CardContent>
        </Card>
    )
}

function CreateMonitorModal(): JSX.Element {
    const { createModalOpen, isCreateMonitorSubmitting } = useValues(uptimeSceneLogic)
    const { setCreateModalOpen } = useActions(uptimeSceneLogic)

    return (
        <Dialog open={createModalOpen} onOpenChange={setCreateModalOpen}>
            <DialogContent>
                <Form logic={uptimeSceneLogic} formKey="createMonitor" enableFormOnSubmit className="contents">
                    <DialogHeader>
                        <DialogTitle>Create monitor</DialogTitle>
                        <DialogDescription>
                            PostHog pings the URL every 5 minutes and computes uptime and latency from the checks.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <MonitorFormFields />
                    </DialogBody>
                    <DialogFooter>
                        <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                        <Button type="submit" variant="primary" loading={isCreateMonitorSubmitting}>
                            Create monitor
                        </Button>
                    </DialogFooter>
                </Form>
            </DialogContent>
        </Dialog>
    )
}

function EditMonitorModal(): JSX.Element {
    const { editingMonitorId, isEditMonitorSubmitting } = useValues(uptimeSceneLogic)
    const { stopEditing } = useActions(uptimeSceneLogic)

    return (
        <Dialog open={editingMonitorId !== null} onOpenChange={(open) => !open && stopEditing()}>
            <DialogContent>
                <Form logic={uptimeSceneLogic} formKey="editMonitor" enableFormOnSubmit className="contents">
                    <DialogHeader>
                        <DialogTitle>Edit monitor</DialogTitle>
                    </DialogHeader>
                    <DialogBody>
                        <MonitorFormFields />
                    </DialogBody>
                    <DialogFooter>
                        <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                        <Button type="submit" variant="primary" loading={isEditMonitorSubmitting}>
                            Save
                        </Button>
                    </DialogFooter>
                </Form>
            </DialogContent>
        </Dialog>
    )
}
