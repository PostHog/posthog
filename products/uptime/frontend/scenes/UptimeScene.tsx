import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement } from '@dnd-kit/modifiers'
import { SortableContext, arrayMove, rectSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconDrag, IconEllipsis, IconPencil, IconPlay, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonCheckbox,
    LemonInput,
    LemonMenu,
    LemonModal,
    LemonTab,
    LemonTable,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    Link,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { IncidentTile } from './IncidentTile'
import { StatusPagesList } from './statusPage/StatusPagesList'
import { statusPagesListLogic } from './statusPage/statusPagesListLogic'
import { UptimeAlerts } from './uptimeAlerts/UptimeAlerts'
import {
    DailyBucket,
    DailyStatus,
    Incident,
    MonitorStatus,
    MonitorSummary,
    OverallStats,
    SuggestedUrl,
    UptimeSceneActiveTab,
    uptimeSceneLogic,
} from './uptimeSceneLogic'

export const scene: SceneExport = {
    component: UptimeScene,
    logic: uptimeSceneLogic,
}

export function UptimeScene(): JSX.Element {
    const { activeTab, suggestedUrls, ongoingIncidentsCount } = useValues(uptimeSceneLogic)
    const { setActiveTab, setCreateModalOpen, setSuggestModalOpen } = useActions(uptimeSceneLogic)
    const { createNewStatusPage } = useActions(statusPagesListLogic)

    const hasSuggestions = suggestedUrls.length > 0

    const tabs: LemonTab<UptimeSceneActiveTab>[] = [
        {
            key: 'monitors',
            label: 'Monitors',
            content: <MonitorsTab />,
        },
        {
            key: 'incidents',
            label: (
                <span className="flex items-center gap-1.5">
                    Declared incidents
                    {ongoingIncidentsCount > 0 && (
                        <span
                            className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-danger text-white text-[10px] font-semibold leading-none"
                            aria-label={`${ongoingIncidentsCount} ongoing declared incidents`}
                        >
                            {ongoingIncidentsCount}
                        </span>
                    )}
                </span>
            ),
            content: <IncidentsTab />,
        },
        {
            key: 'alerts',
            label: 'Alerts',
            content: <UptimeAlerts />,
        },
        {
            key: 'status_pages',
            label: 'Status pages',
            content: <StatusPagesList />,
        },
    ]

    // Use size="small" so the actions slot's height matches the tabs without buttons —
    // keeps the title section the same height when switching tabs.
    const headerActions =
        activeTab === 'monitors' ? (
            <div className="flex gap-2">
                {hasSuggestions && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        data-attr="open-suggest-urls"
                        onClick={() => setSuggestModalOpen(true)}
                    >
                        Add from traffic ({suggestedUrls.length})
                    </LemonButton>
                )}
                <LemonButton
                    type="primary"
                    size="small"
                    data-attr="create-monitor"
                    onClick={() => setCreateModalOpen(true)}
                >
                    Create monitor
                </LemonButton>
            </div>
        ) : activeTab === 'status_pages' ? (
            <LemonButton
                type="primary"
                size="small"
                data-attr="create-status-page"
                onClick={() => createNewStatusPage()}
            >
                New status page
            </LemonButton>
        ) : null

    return (
        <SceneContent>
            <SceneTitleSection
                name="Uptime"
                description="Monitor URLs and view their recent ping history."
                resourceType={{ type: 'default_icon_type' }}
                actions={headerActions}
            />
            <LemonTabs activeKey={activeTab} onChange={(key) => setActiveTab(key)} tabs={tabs} sceneInset />
            <CreateMonitorModal />
            <SuggestUrlsModal />
        </SceneContent>
    )
}

function MonitorsTab(): JSX.Element {
    const { monitorSummaries, monitorSummariesLoading, suggestedUrls, overallStats } = useValues(uptimeSceneLogic)
    const { setSuggestModalOpen, setCreateModalOpen, startEditing, confirmDeleteMonitor, pingNow, reorderMonitors } =
        useActions(uptimeSceneLogic)

    const hasMonitors = monitorSummaries.length > 0
    const topSuggestion = suggestedUrls[0] ?? null

    // 4px activation distance — snappier engagement, while a true click (zero movement)
    // still navigates to the detail page.
    const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }))

    const onDragEnd = (event: DragEndEvent): void => {
        const { active, over } = event
        if (!over || active.id === over.id) {
            return
        }
        const oldIndex = monitorSummaries.findIndex((m) => m.id === active.id)
        const newIndex = monitorSummaries.findIndex((m) => m.id === over.id)
        if (oldIndex === -1 || newIndex === -1) {
            return
        }
        const reordered = arrayMove(monitorSummaries, oldIndex, newIndex)
        reorderMonitors(reordered.map((m) => m.id))
    }

    return (
        <div className="flex flex-col gap-4">
            {hasMonitors && <OverallStatusBanner stats={overallStats} />}

            {!hasMonitors && !monitorSummariesLoading ? (
                <EmptyState
                    topSuggestion={topSuggestion}
                    hasMoreSuggestions={suggestedUrls.length > 1}
                    onOpenSuggest={() => setSuggestModalOpen(true)}
                    onCreateBlank={() => setCreateModalOpen(true)}
                />
            ) : (
                <DndContext sensors={sensors} modifiers={[restrictToParentElement]} onDragEnd={onDragEnd}>
                    <SortableContext items={monitorSummaries.map((m) => m.id)} strategy={rectSortingStrategy}>
                        {/* Fixed responsive column counts with 1fr tracks ensure the grid always
                            fills the parent container so its right edge aligns with the banner.
                            A single tile occupies one cell (1/N of the width), not the full row. */}
                        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                            {monitorSummariesLoading && !hasMonitors
                                ? Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} />)
                                : monitorSummaries.map((monitor) => (
                                      <MonitorTile
                                          key={monitor.id}
                                          monitor={monitor}
                                          onPingNow={() => pingNow(monitor.id)}
                                          onEdit={() => startEditing(monitor)}
                                          onDelete={() => confirmDeleteMonitor({ id: monitor.id, name: monitor.name })}
                                      />
                                  ))}
                        </div>
                    </SortableContext>
                </DndContext>
            )}
            <EditMonitorModal />
        </div>
    )
}

function IncidentsTab(): JSX.Element {
    const { ongoingIncidents, resolvedIncidents, incidentsLoading, monitorSummaries } = useValues(uptimeSceneLogic)
    const { startEditingIncident, promptResolveIncident, reopenIncident, confirmDeleteIncident } =
        useActions(uptimeSceneLogic)

    const monitorsById = new Map(monitorSummaries.map((m: MonitorSummary) => [m.id, m]))

    if (incidentsLoading && ongoingIncidents.length === 0 && resolvedIncidents.length === 0) {
        return <div className="text-secondary text-sm">Loading declared incidents…</div>
    }

    if (ongoingIncidents.length === 0 && resolvedIncidents.length === 0) {
        return (
            <LemonCard hoverEffect={false} className="flex flex-col items-center gap-2 p-8 text-center">
                <div className="text-xl font-semibold">No declared incidents yet</div>
                <div className="text-secondary max-w-md">
                    Open a monitor's detail page to declare an incident. Ongoing declared incidents will appear here.
                </div>
            </LemonCard>
        )
    }

    const renderTile = (incident: Incident): JSX.Element => (
        <IncidentTile
            key={incident.id}
            incident={incident}
            monitorName={monitorsById.get(incident.monitor_id)?.name}
            linkToMonitor
            onEdit={() => startEditingIncident(incident)}
            onResolve={() => promptResolveIncident(incident)}
            onReopen={() => reopenIncident(incident.id)}
            onDelete={() => confirmDeleteIncident({ id: incident.id, name: incident.name })}
        />
    )

    return (
        <div className="flex flex-col gap-6">
            {ongoingIncidents.length > 0 && (
                <section className="flex flex-col gap-3">
                    <h3 className="text-base font-semibold m-0">Ongoing</h3>
                    <div
                        className="grid gap-4"
                        style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 360px))' }}
                    >
                        {ongoingIncidents.map(renderTile)}
                    </div>
                </section>
            )}
            {resolvedIncidents.length > 0 && (
                <section className="flex flex-col gap-3">
                    <h3 className="text-base font-semibold m-0">Resolved</h3>
                    <div
                        className="grid gap-4"
                        style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 360px))' }}
                    >
                        {resolvedIncidents.map(renderTile)}
                    </div>
                </section>
            )}
            <EditIncidentModal />
        </div>
    )
}

function EditIncidentModal(): JSX.Element {
    const { editingIncidentId, isEditIncidentFormSubmitting, editingIncident } = useValues(uptimeSceneLogic)
    const { setEditIncidentValue, submitEditIncident, stopEditingIncident } = useActions(uptimeSceneLogic)

    const showResolutionField = editingIncident?.resolved_at != null

    return (
        <LemonModal
            isOpen={editingIncidentId !== null}
            onClose={stopEditingIncident}
            title="Edit declared incident"
            footer={
                <LemonButton type="primary" loading={isEditIncidentFormSubmitting} onClick={() => submitEditIncident()}>
                    Save
                </LemonButton>
            }
        >
            <Form logic={uptimeSceneLogic} formKey="editIncident" className="deprecated-space-y-4">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="API outage" onChange={(v) => setEditIncidentValue('name', v)} />
                </LemonField>
                <LemonField name="description" label="Description">
                    <LemonTextArea
                        placeholder="What's happening?"
                        rows={4}
                        onChange={(v) => setEditIncidentValue('description', v)}
                    />
                </LemonField>
                {showResolutionField && (
                    <LemonField name="resolution_note" label="Resolution">
                        <LemonTextArea
                            placeholder="What fixed it?"
                            rows={3}
                            onChange={(v) => setEditIncidentValue('resolution_note', v)}
                        />
                    </LemonField>
                )}
            </Form>
        </LemonModal>
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
                    label="Uptime (30d)"
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
    onPingNow,
    onEdit,
    onDelete,
}: {
    monitor: MonitorSummary
    onPingNow: () => void
    onEdit: () => void
    onDelete: () => void
}): JSX.Element {
    const { setNodeRef, attributes, listeners, transform, transition, isDragging } = useSortable({
        id: monitor.id,
    })

    // Interactive children stopPropagation so clicking them doesn't also fire the
    // tile-wide navigation.
    const stop = (e: React.MouseEvent): void => e.stopPropagation()

    return (
        <LemonCard
            // Hover effect plays a CSS transition that fights with dnd-kit's transform
            // during a drag, making the motion feel sluggish.
            hoverEffect={!isDragging}
            onClick={() => router.actions.push(urls.uptimeMonitor(monitor.id))}
            className="flex flex-col gap-3 p-4"
            ref={setNodeRef}
            // dnd-kit needs inline transform/transition styles; tailwind classes won't work here.
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
                opacity: isDragging ? 0.6 : undefined,
                zIndex: isDragging ? 10 : undefined,
                cursor: isDragging ? 'grabbing' : undefined,
            }}
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
                    <LemonMenu
                        items={[
                            { label: 'Edit', icon: <IconPencil />, onClick: onEdit },
                            { label: 'Delete', icon: <IconTrash />, status: 'danger', onClick: onDelete },
                        ]}
                    >
                        <LemonButton size="xsmall" icon={<IconEllipsis />} aria-label="Monitor actions" />
                    </LemonMenu>
                    <LemonButton
                        size="xsmall"
                        icon={<IconDrag />}
                        aria-label="Drag to reorder"
                        tooltip="Drag to reorder"
                        // Pointer-down events are forwarded to dnd-kit via these listeners;
                        // they intentionally bypass the parent card click handler.
                        {...attributes}
                        {...listeners}
                        // touch-none prevents the browser from scrolling on touch-and-drag,
                        // which would otherwise cancel the dnd-kit gesture mid-motion.
                        className="cursor-grab active:cursor-grabbing touch-none"
                    />
                </div>
            </div>

            <div className="flex items-baseline justify-between gap-2">
                <div className="flex flex-col">
                    <span className="text-2xl font-semibold">
                        {monitor.uptime_30d !== null ? formatPercent(monitor.uptime_30d) : '—'}
                    </span>
                    <span className="text-xs text-secondary">30d uptime</span>
                </div>
                <div className="flex flex-col items-end">
                    <span className="text-sm font-medium">
                        {monitor.avg_latency_24h_ms !== null ? `${monitor.avg_latency_24h_ms} ms` : '—'}
                    </span>
                    <span className="text-xs text-secondary">avg 24h</span>
                </div>
            </div>

            <StatusTimeline buckets={monitor.daily_buckets} />

            <div className="flex items-center justify-between text-xs text-secondary">
                <span>
                    {monitor.last_ping_at ? `Last checked ${dayjs(monitor.last_ping_at).fromNow()}` : 'No checks yet'}
                </span>
                <LemonButton
                    size="xsmall"
                    icon={<IconPlay />}
                    onClick={(e) => {
                        stop(e)
                        onPingNow()
                    }}
                >
                    Ping now
                </LemonButton>
            </div>
        </LemonCard>
    )
}

function StatusTimeline({ buckets }: { buckets: DailyBucket[] }): JSX.Element {
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

function StatusDot({ status, size = 'md' }: { status: MonitorStatus; size?: 'md' | 'lg' }): JSX.Element {
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

function EmptyState({
    topSuggestion,
    hasMoreSuggestions,
    onOpenSuggest,
    onCreateBlank,
}: {
    topSuggestion: SuggestedUrl | null
    hasMoreSuggestions: boolean
    onOpenSuggest: () => void
    onCreateBlank: () => void
}): JSX.Element {
    const { quickAddSuggestion } = useActions(uptimeSceneLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonCard hoverEffect={false} className="flex flex-col items-center gap-2 p-8 text-center">
                <div className="text-xl font-semibold">No monitors yet</div>
                <div className="text-secondary max-w-md">
                    {topSuggestion
                        ? 'Start with a URL we found in your traffic below, or add one manually.'
                        : 'Add a URL to start tracking its uptime, latency, and response codes.'}
                </div>
                <LemonButton type="primary" icon={<IconPlus />} onClick={onCreateBlank} size="small">
                    Create monitor
                </LemonButton>
            </LemonCard>
            {topSuggestion && (
                <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    <GhostTile suggestion={topSuggestion} onAdd={() => quickAddSuggestion(topSuggestion)} />
                    {hasMoreSuggestions && (
                        <LemonCard
                            hoverEffect
                            onClick={onOpenSuggest}
                            className="flex flex-col items-center justify-center gap-2 p-6 text-center border-dashed"
                        >
                            <div className="font-semibold">See all suggestions</div>
                            <div className="text-xs text-secondary">More URLs detected in your traffic</div>
                        </LemonCard>
                    )}
                </div>
            )}
        </div>
    )
}

function GhostTile({ suggestion, onAdd }: { suggestion: SuggestedUrl; onAdd: () => void }): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4 border-dashed bg-surface-secondary/50">
            <div className="flex items-center justify-between gap-2">
                <div className="font-semibold truncate">{suggestion.host}</div>
                <LemonTag type="muted" size="small">
                    Suggested
                </LemonTag>
            </div>
            <div className="text-xs text-secondary truncate" title={suggestion.url}>
                {suggestion.url}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-secondary">
                <span>{humanFriendlyNumber(suggestion.event_count)} pageviews</span>
                <span>{suggestion.unique_paths} paths</span>
            </div>
            <LemonButton type="primary" icon={<IconPlus />} onClick={onAdd} fullWidth>
                Start monitoring {suggestion.host}
            </LemonButton>
        </LemonCard>
    )
}

function CreateMonitorModal(): JSX.Element {
    const { createModalOpen, isCreateMonitorFormSubmitting, topSuggestedUrls } = useValues(uptimeSceneLogic)
    const { setCreateMonitorValue, submitCreateMonitor, setCreateModalOpen } = useActions(uptimeSceneLogic)

    return (
        <LemonModal
            isOpen={createModalOpen}
            onClose={() => setCreateModalOpen(false)}
            title="Create monitor"
            footer={
                <LemonButton
                    type="primary"
                    loading={isCreateMonitorFormSubmitting}
                    onClick={() => submitCreateMonitor()}
                >
                    Create
                </LemonButton>
            }
        >
            <Form logic={uptimeSceneLogic} formKey="createMonitor" className="deprecated-space-y-4">
                {topSuggestedUrls.length > 0 && (
                    <div className="flex flex-col gap-2">
                        <div className="text-sm text-secondary">Suggested from your traffic</div>
                        <div className="flex flex-wrap gap-2">
                            {topSuggestedUrls.map((s: SuggestedUrl) => (
                                <LemonButton
                                    key={s.url}
                                    type="secondary"
                                    size="small"
                                    onClick={() => {
                                        setCreateMonitorValue('url', s.url)
                                        setCreateMonitorValue('name', s.host)
                                    }}
                                    tooltip={`${humanFriendlyNumber(s.event_count)} pageviews, ${s.unique_paths} paths`}
                                >
                                    {s.host}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                )}
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
    const { editingMonitorId, isEditMonitorFormSubmitting } = useValues(uptimeSceneLogic)
    const { setEditMonitorValue, submitEditMonitor, stopEditing } = useActions(uptimeSceneLogic)

    return (
        <LemonModal
            isOpen={editingMonitorId !== null}
            onClose={stopEditing}
            title="Edit monitor"
            footer={
                <LemonButton type="primary" loading={isEditMonitorFormSubmitting} onClick={() => submitEditMonitor()}>
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

function SuggestUrlsModal(): JSX.Element {
    const { suggestModalOpen, suggestedUrls, suggestedUrlsLoading, selectedSuggestions } = useValues(uptimeSceneLogic)
    const { setSuggestModalOpen, toggleSuggestion, clearSelectedSuggestions, bulkAddSelected } =
        useActions(uptimeSceneLogic)

    const selectedSet = new Set(selectedSuggestions)
    const allSelected = suggestedUrls.length > 0 && selectedSuggestions.length === suggestedUrls.length

    return (
        <LemonModal
            isOpen={suggestModalOpen}
            onClose={() => setSuggestModalOpen(false)}
            title="Add monitors from traffic"
            description="Pick URLs detected from $pageview events. Already-monitored hosts are excluded."
            width={760}
            footer={
                <div className="flex w-full items-center justify-between">
                    <div className="text-sm text-secondary">
                        {selectedSuggestions.length} of {suggestedUrls.length} selected
                    </div>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={() => setSuggestModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            disabledReason={selectedSuggestions.length === 0 ? 'Select at least one URL' : undefined}
                            onClick={() => bulkAddSelected()}
                        >
                            Add {selectedSuggestions.length || ''} monitor
                            {selectedSuggestions.length === 1 ? '' : 's'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonTable
                loading={suggestedUrlsLoading}
                dataSource={suggestedUrls}
                rowKey="url"
                columns={[
                    {
                        title: (
                            <LemonCheckbox
                                checked={allSelected}
                                onChange={() => {
                                    if (allSelected) {
                                        clearSelectedSuggestions()
                                    } else {
                                        suggestedUrls.forEach((s: SuggestedUrl) => {
                                            if (!selectedSet.has(s.url)) {
                                                toggleSuggestion(s.url)
                                            }
                                        })
                                    }
                                }}
                            />
                        ),
                        key: 'select',
                        width: 0,
                        render: (_, row: SuggestedUrl) => (
                            <LemonCheckbox
                                checked={selectedSet.has(row.url)}
                                onChange={() => toggleSuggestion(row.url)}
                            />
                        ),
                    },
                    {
                        title: 'URL',
                        dataIndex: 'url',
                        render: (_, row: SuggestedUrl) => (
                            <div className="flex flex-col">
                                <span className="font-medium">{row.host}</span>
                                <span className="text-xs text-secondary">{row.url}</span>
                            </div>
                        ),
                    },
                    {
                        title: 'Pageviews',
                        dataIndex: 'event_count',
                        sorter: (a: SuggestedUrl, b: SuggestedUrl) => a.event_count - b.event_count,
                        render: (_, row: SuggestedUrl) => humanFriendlyNumber(row.event_count),
                    },
                    {
                        title: 'Unique paths',
                        dataIndex: 'unique_paths',
                        sorter: (a: SuggestedUrl, b: SuggestedUrl) => a.unique_paths - b.unique_paths,
                    },
                    {
                        title: 'Last seen',
                        dataIndex: 'last_seen',
                        sorter: (a: SuggestedUrl, b: SuggestedUrl) =>
                            dayjs(a.last_seen).valueOf() - dayjs(b.last_seen).valueOf(),
                        render: (_, row: SuggestedUrl) => dayjs(row.last_seen).fromNow(),
                    },
                ]}
                emptyState="No suggestions yet. Once we see $pageview events, pingable hosts will appear here."
            />
        </LemonModal>
    )
}

function statusLabel(status: MonitorStatus): string {
    switch (status) {
        case 'up':
            return 'Operational'
        case 'down':
            return 'Down'
        case 'no_data':
            return 'No data'
    }
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
