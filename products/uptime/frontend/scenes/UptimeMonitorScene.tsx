import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconArrowLeft, IconEllipsis, IconPencil, IconPulse, IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Dot,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Table,
    TableBody,
    TableCell,
    TableEmpty,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { DeleteMonitorDialog } from '../components/DeleteMonitorDialog'
import {
    formatDuration,
    formatPercent,
    monitorStatusDotVariant,
    monitorStatusLabel,
} from '../components/monitorDisplay'
import { MonitorFormFields } from '../components/MonitorFormFields'
import { StatusTimeline } from '../components/StatusTimeline'
import type { OutageDTOApi, PingDTOApi } from '../generated/api.schemas'
import { uptimeMonitorSceneLogic } from './uptimeMonitorSceneLogic'

export const scene: SceneExport = {
    component: UptimeMonitorScene,
    logic: uptimeMonitorSceneLogic,
}

export function UptimeMonitorScene(): JSX.Element {
    const {
        summary,
        summaryLoading,
        pings,
        pingsLoading,
        outages,
        outagesLoading,
        deleteConfirmOpen,
        monitorDeleting,
    } = useValues(uptimeMonitorSceneLogic)
    const { setEditModalOpen, confirmDeleteMonitor, cancelDeleteMonitor, deleteMonitor } =
        useActions(uptimeMonitorSceneLogic)

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
                <div data-quill>
                    <Card>
                        <CardContent>
                            <Empty>
                                <EmptyHeader>
                                    <EmptyMedia variant="icon">
                                        <IconPulse />
                                    </EmptyMedia>
                                    <EmptyTitle>Monitor not found</EmptyTitle>
                                    <EmptyDescription>It may have been deleted.</EmptyDescription>
                                </EmptyHeader>
                                <EmptyContent>
                                    <Button variant="primary" onClick={() => router.actions.push(urls.uptime())}>
                                        <IconArrowLeft />
                                        Back to monitors
                                    </Button>
                                </EmptyContent>
                            </Empty>
                        </CardContent>
                    </Card>
                </div>
            </SceneContent>
        )
    }

    const cleanDays = summary.daily_buckets.filter((b) => b.status === 'up').length

    return (
        <SceneContent>
            {/* No description prop — kills both the URL subtitle and the collapse toggle
                that auto-renders next to descriptions. The URL is still visible inside the
                status banner below. */}
            <SceneTitleSection
                name={summary.name}
                resourceType={{ type: 'uptime' }}
                actions={
                    <div className="flex gap-2 self-center" data-quill>
                        <Button variant="outline" onClick={() => setEditModalOpen(true)}>
                            <IconPencil />
                            Edit
                        </Button>
                        <DropdownMenu>
                            <DropdownMenuTrigger
                                render={<Button variant="outline" size="icon" aria-label="More actions" />}
                            >
                                <IconEllipsis />
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end">
                                <DropdownMenuItem variant="destructive" onClick={() => confirmDeleteMonitor()}>
                                    <IconTrash />
                                    Delete monitor
                                </DropdownMenuItem>
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                }
            />

            <EditMonitorModal />
            <DeleteMonitorDialog
                monitorName={deleteConfirmOpen ? summary.name : null}
                deleting={monitorDeleting}
                onConfirm={() => deleteMonitor()}
                onCancel={cancelDeleteMonitor}
            />

            <div className="flex flex-col gap-4" data-quill>
                <Card size="sm">
                    <CardContent className="flex flex-col gap-3">
                        <div className="flex flex-wrap items-center gap-2">
                            <Dot variant={monitorStatusDotVariant(summary.status)} pulse={summary.status === 'down'} />
                            <Text
                                size="sm"
                                weight="semibold"
                                variant={summary.status === 'down' ? 'destructive' : 'default'}
                                render={<span />}
                            >
                                {monitorStatusLabel(summary.status)}
                            </Text>
                            <Badge variant={monitorStatusDotVariant(summary.status)}>
                                {summary.last_ping_at
                                    ? `Last checked ${dayjs(summary.last_ping_at).fromNow()}`
                                    : 'No checks yet'}
                            </Badge>
                        </div>
                        <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
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
                                    <Link
                                        to={summary.url}
                                        target="_blank"
                                        className="text-base font-medium hover:underline"
                                    >
                                        {summary.url}
                                    </Link>
                                }
                            />
                        </div>
                    </CardContent>
                </Card>

                <Card size="sm">
                    <CardHeader>
                        <CardTitle>90-day uptime history</CardTitle>
                        <CardDescription>
                            {cleanDays} of {summary.daily_buckets.length} days clean
                        </CardDescription>
                    </CardHeader>
                    <CardContent>
                        <StatusTimeline buckets={summary.daily_buckets} />
                    </CardContent>
                </Card>

                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                    <Card size="sm" flush>
                        <CardHeader>
                            <CardTitle>Recent pings</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <PingsTable pings={pings} loading={pingsLoading} />
                        </CardContent>
                    </Card>
                    <Card size="sm">
                        <CardHeader>
                            <CardTitle>Outages</CardTitle>
                            <CardDescription>Last 7 days</CardDescription>
                        </CardHeader>
                        <CardContent>
                            <OutagesList outages={outages} loading={outagesLoading} />
                        </CardContent>
                    </Card>
                </div>
            </div>
        </SceneContent>
    )
}

function PingsTable({ pings, loading }: { pings: PingDTOApi[]; loading: boolean }): JSX.Element {
    return (
        <Table size="sm" fullWidth>
            <TableHeader>
                <TableRow>
                    <TableHead expand>When</TableHead>
                    <TableHead>Outcome</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead align="right">Latency</TableHead>
                </TableRow>
            </TableHeader>
            {loading && pings.length === 0 ? (
                <TableBody>
                    <TableRow>
                        <TableCell colSpan={4}>
                            <div className="flex flex-col gap-2 py-1">
                                {Array.from({ length: 4 }).map((_, i) => (
                                    <Skeleton key={i} className="h-3.5 w-full" />
                                ))}
                            </div>
                        </TableCell>
                    </TableRow>
                </TableBody>
            ) : pings.length === 0 ? (
                <TableEmpty className="py-6">
                    <Text size="xs" variant="muted" render={<span />}>
                        No pings recorded yet.
                    </Text>
                </TableEmpty>
            ) : (
                <TableBody>
                    {pings.map((ping) => (
                        <TableRow key={`${ping.timestamp}-${ping.status_code ?? 'none'}`}>
                            <TableCell expand className="whitespace-nowrap">
                                {dayjs(ping.timestamp).fromNow()}
                            </TableCell>
                            <TableCell>
                                <Badge variant={ping.outcome === 'success' ? 'success' : 'destructive'}>
                                    {ping.outcome}
                                </Badge>
                            </TableCell>
                            <TableCell>{ping.status_code ? String(ping.status_code) : '—'}</TableCell>
                            <TableCell align="right" className="whitespace-nowrap">
                                {ping.latency_ms} ms
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            )}
        </Table>
    )
}

function OutagesList({ outages, loading }: { outages: OutageDTOApi[]; loading: boolean }): JSX.Element {
    if (loading && outages.length === 0) {
        return <Skeleton className="h-24 w-full" />
    }

    if (outages.length === 0) {
        return (
            <div className="flex justify-center py-8">
                <Text size="xs" variant="muted" render={<span />} className="max-w-xs text-center">
                    No outages detected in the last 7 days. All clear.
                </Text>
            </div>
        )
    }

    return (
        <ItemGroup>
            {outages.map((outage) => (
                <OutageItem key={`${outage.started_at}-${outage.resolved_at ?? 'ongoing'}`} outage={outage} />
            ))}
        </ItemGroup>
    )
}

function OutageItem({ outage }: { outage: OutageDTOApi }): JSX.Element {
    const ongoing = !outage.resolved_at
    const end = outage.resolved_at ? dayjs(outage.resolved_at) : dayjs()
    const durationLabel = formatDuration(dayjs(outage.started_at), end)

    return (
        <Item variant="outline" size="sm">
            <ItemMedia>
                <Dot variant={ongoing ? 'destructive' : 'success'} pulse={ongoing} />
            </ItemMedia>
            <ItemContent>
                <ItemTitle>{ongoing ? `Ongoing · ${durationLabel}` : durationLabel}</ItemTitle>
                <ItemDescription>
                    Started {dayjs(outage.started_at).fromNow()}
                    {outage.resolved_at && ` · resolved ${dayjs(outage.resolved_at).fromNow()}`}
                </ItemDescription>
            </ItemContent>
            <Text size="xs" variant="muted" render={<span />} className="shrink-0">
                {outage.fail_count} failed{outage.last_status_code ? ` · ${outage.last_status_code}` : ''}
            </Text>
        </Item>
    )
}

function EditMonitorModal(): JSX.Element {
    const { editModalOpen, isEditMonitorSubmitting } = useValues(uptimeMonitorSceneLogic)
    const { setEditModalOpen } = useActions(uptimeMonitorSceneLogic)

    return (
        <Dialog open={editModalOpen} onOpenChange={setEditModalOpen}>
            <DialogContent>
                <Form logic={uptimeMonitorSceneLogic} formKey="editMonitor" enableFormOnSubmit className="contents">
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

function Metric({ label, value }: { label: string; value: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <Text size="xs" variant="muted" render={<span />}>
                {label}
            </Text>
            <span className="text-xl font-semibold">{value}</span>
        </div>
    )
}

function DetailSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-4" data-quill>
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-48 w-full" />
        </div>
    )
}
