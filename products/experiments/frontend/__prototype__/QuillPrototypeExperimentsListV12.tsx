/** Scratch prototype v12: the experiment list on quill, with a list and a timeline view. Not committed. */
import type { ColumnDef, RowSelectionState, SortingState } from '@tanstack/react-table'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
    IconCalendar,
    IconEllipsis,
    IconFlask,
    IconList,
    IconMessage,
    IconSearch,
    IconTrending,
    IconWrench,
} from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Badge,
    Button,
    Card,
    DataTable,
    Dot,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    FilterClearItem,
    FilterMenuTrigger,
    FilterRadioSubMenu,
    FilterSearchSubMenu,
    Progress,
    Tabs,
    TabsList,
    TabsTrigger,
    Text,
    ToastProvider,
    ToggleGroup,
    ToggleGroupItem,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    toast,
} from '@posthog/quill'

import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'

import { QuillSceneHeader } from '~/layout/scenes/components/QuillSceneHeader'

import {
    CONCLUSION_LABEL,
    PrototypeExperimentsTimeline,
    STATUS_BADGE,
    STATUS_LABEL,
    TIMELINE_GROUP,
    TIMELINE_ZOOM,
    TimelineControls,
    type TimelineGroup,
    type TimelineZoom,
} from './PrototypeExperimentsTimeline'
import {
    ALL_TAGS,
    type Conclusion,
    LIST_EXPERIMENTS,
    LIST_STATUS,
    LIST_TODAY,
    type ListExperiment,
    type ListStatus,
    PEOPLE,
    VELOCITY,
} from './prototypeListData'
import { SHELL_STATE, type ShellState } from './QuillPrototypeExperimentPageV12'

export const LIST_VIEW = { list: 'list', timeline: 'timeline' } as const
export type ListView = (typeof LIST_VIEW)[keyof typeof LIST_VIEW]

/** Small on purpose, so the prototype shows the pagination. The product loads 100 per page. */
const PAGE_SIZE = 10
const VISIBLE_TAGS = 2
/** Below this table width the dates and tags go, so status, result and actions stay on screen without a sideways scroll. */
const NARROW_TABLE_PX = 1200
const NARROW_HIDDEN_COLUMNS = ['created_at', 'start_date', 'tags']

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
    const ref = useRef<T>(null)
    const [width, setWidth] = useState(0)
    useEffect(() => {
        if (!ref.current) {
            return
        }
        const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
        observer.observe(ref.current)
        return () => observer.disconnect()
    }, [])
    return [ref, width]
}

const today = dayjs(LIST_TODAY)

const STATUS_OPTIONS = [
    { value: 'all', label: 'All statuses' },
    ...Object.values(LIST_STATUS).map((status) => ({ value: status, label: STATUS_LABEL[status] })),
]
const ARCHIVED_OPTIONS = [
    { value: 'active', label: 'Active' },
    { value: 'archived', label: 'Archived' },
]

const CONCLUSION_DOT: Record<Conclusion, 'success' | 'destructive' | 'default' | 'warning'> = {
    won: 'success',
    lost: 'destructive',
    inconclusive: 'default',
    'stopped-early': 'warning',
    invalid: 'default',
}

export interface ListFilters {
    search: string
    status: ListStatus | 'all'
    createdBy: string[]
    tags: string[]
    excludedTags: string[]
    archived: boolean
}

export const DEFAULT_FILTERS: ListFilters = {
    search: '',
    status: 'all',
    createdBy: [],
    tags: [],
    excludedTags: [],
    archived: false,
}

function initials(name: string): string {
    return name
        .split(' ')
        .map((part) => part[0])
        .join('')
}

function duration(experiment: ListExperiment): number | null {
    if (!experiment.startDate) {
        return null
    }
    return dayjs(experiment.endDate ?? today).diff(experiment.startDate, 'day')
}

function applyFilters(experiments: ListExperiment[], filters: ListFilters): ListExperiment[] {
    const search = filters.search.trim().toLowerCase()
    return experiments.filter(
        (experiment) =>
            !!experiment.archived === filters.archived &&
            (!search ||
                experiment.name.toLowerCase().includes(search) ||
                experiment.flagKey.toLowerCase().includes(search)) &&
            (filters.status === 'all' || experiment.status === filters.status) &&
            (filters.createdBy.length === 0 || filters.createdBy.includes(experiment.createdBy)) &&
            (filters.tags.length === 0 || filters.tags.some((tag) => experiment.tags.includes(tag))) &&
            !filters.excludedTags.some((tag) => experiment.tags.includes(tag))
    )
}

const SORTERS: Record<string, (experiment: ListExperiment) => string | number> = {
    name: (experiment) => experiment.name.toLowerCase(),
    created_at: (experiment) => experiment.createdAt,
    start_date: (experiment) => experiment.startDate ?? '',
    duration: (experiment) => duration(experiment) ?? -1,
    status: (experiment) => Object.values(LIST_STATUS).indexOf(experiment.status),
}

function sortRows(experiments: ListExperiment[], sorting: SortingState): ListExperiment[] {
    const [sort] = sorting
    const key = sort && SORTERS[sort.id]
    if (!key) {
        return experiments
    }
    return [...experiments].sort((a, b) => {
        const order = key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0
        return sort.desc ? -order : order
    })
}

/** Placeholder for the rail and the Products sidebar, so the scene gets its real width. */
function FakeShell({ shell }: { shell: ShellState }): JSX.Element | null {
    if (shell === SHELL_STATE.phone) {
        return null
    }
    return (
        <>
            <div className="flex w-15 shrink-0 flex-col items-center gap-3 border-r border-border bg-chrome py-3">
                {Array.from({ length: 5 }, (_, index) => (
                    <div key={index} className="size-8 rounded-md bg-fill-hover" />
                ))}
            </div>
            {shell === SHELL_STATE.sidebarOpen && (
                <div className="flex w-72 shrink-0 flex-col gap-2 border-r border-border bg-chrome p-3">
                    <div className="-mx-3 -mt-3 mb-1 h-10.5 border-b border-border" />
                    {Array.from({ length: 12 }, (_, index) => (
                        <div key={index} className="h-5 rounded-sm bg-fill-hover" />
                    ))}
                </div>
            )}
        </>
    )
}

function SceneActions(): JSX.Element {
    return (
        <>
            <Button size="icon" aria-label="Setup inspector" tooltip="Setup inspector" data-attr="setup-inspector">
                <IconWrench />
            </Button>
            <Button
                size="icon"
                aria-label="Give feedback"
                tooltip="Give feedback"
                data-attr="experiments-feedback-button"
            >
                <IconMessage />
            </Button>
            <Button variant="primary" data-attr="create-experiment" tooltip="New experiment">
                New experiment
            </Button>
        </>
    )
}

/** The team's launch pace, kept from today's list. It moves under the toolbar when the scene is narrow. */
function VelocityStats(): JSX.Element {
    const stats = [
        { value: VELOCITY.launched, label: 'launched (30d)', change: VELOCITY.launchedChange },
        { value: VELOCITY.running, label: 'running' },
        { value: VELOCITY.completed, label: 'completed (30d)' },
    ]
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <div tabIndex={0} className="flex items-center gap-4 rounded-md px-1" data-attr="velocity-stats" />
                }
            >
                {stats.map((stat) => (
                    <span key={stat.label} className="flex items-baseline gap-1">
                        <Text size="sm" weight="semibold" render={<span />}>
                            {stat.value}
                        </Text>
                        {stat.change !== undefined && (
                            <span className="flex items-center gap-0.5 text-xs font-medium text-success-foreground [&_svg]:size-3.5">
                                <IconTrending />
                                {`${stat.change}%`}
                            </span>
                        )}
                        <Text size="xs" variant="muted" render={<span />}>
                            {stat.label}
                        </Text>
                    </span>
                ))}
            </TooltipTrigger>
            <TooltipContent side="bottom" align="end" className="max-w-72">
                How many experiments your team launches, runs and completes. Launched is compared with the 30 days
                before.
            </TooltipContent>
        </Tooltip>
    )
}

function ListFilterMenu({
    filters,
    onChange,
}: {
    filters: ListFilters
    onChange: (next: Partial<ListFilters>) => void
}): JSX.Element {
    const active =
        filters.status !== 'all' ||
        filters.createdBy.length > 0 ||
        filters.tags.length > 0 ||
        filters.excludedTags.length > 0 ||
        filters.archived
    const tagOptions = ALL_TAGS.map((tag) => ({ value: tag, label: tag }))
    return (
        <DropdownMenu>
            <FilterMenuTrigger active={active} dataAttr="experiments-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterRadioSubMenu
                    label="Status"
                    options={STATUS_OPTIONS}
                    value={filters.status}
                    defaultValue="all"
                    onChange={(status) => onChange({ status: status as ListFilters['status'] })}
                />
                <FilterSearchSubMenu
                    label="Created by"
                    allLabel="Any user"
                    pluralNoun="people"
                    options={PEOPLE.map((person) => ({
                        value: person,
                        label: person,
                        icon: (
                            <Avatar size="xs">
                                <AvatarFallback>{initials(person)}</AvatarFallback>
                            </Avatar>
                        ),
                    }))}
                    selected={filters.createdBy}
                    onChange={(createdBy) => onChange({ createdBy })}
                    searchPlaceholder="Search people"
                    emptyText="No one matches"
                />
                <FilterSearchSubMenu
                    label="Tags"
                    allLabel="Any tag"
                    pluralNoun="tags"
                    options={tagOptions}
                    selected={filters.tags}
                    onChange={(tags) => onChange({ tags })}
                    searchPlaceholder="Search tags"
                    emptyText="No tag matches"
                />
                <FilterSearchSubMenu
                    label="Exclude tags"
                    allLabel="No tags"
                    pluralNoun="tags"
                    options={tagOptions}
                    selected={filters.excludedTags}
                    onChange={(excludedTags) => onChange({ excludedTags })}
                    searchPlaceholder="Search tags"
                    emptyText="No tag matches"
                />
                <DropdownMenuSeparator />
                <FilterRadioSubMenu
                    label="Archived"
                    options={ARCHIVED_OPTIONS}
                    value={filters.archived ? 'archived' : 'active'}
                    defaultValue="active"
                    onChange={(value) => onChange({ archived: value === 'archived' })}
                />
                <FilterClearItem
                    active={active}
                    onClear={() => onChange({ ...DEFAULT_FILTERS, search: filters.search })}
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/** Shows each filter that is on, so the user sees why rows are missing without opening the menu. */
function ActiveFilters({
    filters,
    onChange,
}: {
    filters: ListFilters
    onChange: (next: Partial<ListFilters>) => void
}): JSX.Element | null {
    const chips: { key: string; label: string; clear: Partial<ListFilters> }[] = []
    if (filters.status !== 'all') {
        chips.push({ key: 'status', label: `Status: ${STATUS_LABEL[filters.status]}`, clear: { status: 'all' } })
    }
    if (filters.createdBy.length) {
        chips.push({ key: 'createdBy', label: `Created by: ${filters.createdBy.join(', ')}`, clear: { createdBy: [] } })
    }
    if (filters.tags.length) {
        chips.push({ key: 'tags', label: `Tags: ${filters.tags.join(', ')}`, clear: { tags: [] } })
    }
    if (filters.excludedTags.length) {
        chips.push({
            key: 'excluded',
            label: `Without: ${filters.excludedTags.join(', ')}`,
            clear: { excludedTags: [] },
        })
    }
    if (filters.archived) {
        chips.push({ key: 'archived', label: 'Archived', clear: { archived: false } })
    }
    if (!chips.length) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            {chips.map((chip) => (
                <Button
                    key={chip.key}
                    size="xs"
                    variant="outline"
                    onClick={() => onChange(chip.clear)}
                    aria-label={`Remove filter ${chip.label}`}
                >
                    {chip.label}
                    <span aria-hidden className="text-muted-foreground">
                        ×
                    </span>
                </Button>
            ))}
        </div>
    )
}

function RowActions({ experiment }: { experiment: ListExperiment }): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon-sm"
                        aria-label={`More actions for ${experiment.name}`}
                        data-attr="experiment-row-more"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <DropdownMenuItem>View</DropdownMenuItem>
                <DropdownMenuItem disabled={experiment.legacy}>Duplicate</DropdownMenuItem>
                <DropdownMenuItem disabled={experiment.legacy}>Copy to project</DropdownMenuItem>
                <DropdownMenuItem>Create survey</DropdownMenuItem>
                {experiment.archived ? (
                    <DropdownMenuItem>Unarchive experiment</DropdownMenuItem>
                ) : (
                    experiment.status === LIST_STATUS.complete && (
                        <DropdownMenuItem>Archive experiment</DropdownMenuItem>
                    )
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem variant="destructive">Delete experiment</DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function RemainingCell({ experiment }: { experiment: ListExperiment }): JSX.Element {
    if (experiment.status === LIST_STATUS.complete || experiment.status === LIST_STATUS.draft) {
        return (
            <Text size="xs" variant="muted">
                –
            </Text>
        )
    }
    if (experiment.remainingDays === undefined) {
        return (
            <Text size="xs" variant="muted" className="whitespace-nowrap">
                Not enough data
            </Text>
        )
    }
    if (experiment.remainingDays === 0) {
        return (
            <span className="flex items-center gap-2">
                <Progress value={100} variant="success" className="w-12" />
                <Text size="xs" className="whitespace-nowrap text-success-foreground">
                    Target reached
                </Text>
            </span>
        )
    }
    const elapsed = duration(experiment) ?? 0
    return (
        <span className="flex items-center gap-2">
            <Progress value={(elapsed / (elapsed + experiment.remainingDays)) * 100} className="w-12" />
            <Text size="xs" variant="muted" className="whitespace-nowrap">
                {`~${experiment.remainingDays} days left`}
            </Text>
        </span>
    )
}

function NameCell({ experiment }: { experiment: ListExperiment }): JSX.Element {
    return (
        <div className="flex w-72 min-w-full flex-col gap-0.5">
            <div className="flex min-w-0 flex-wrap items-center gap-1">
                <LinkPrimitive
                    to="#"
                    onClick={(event) => event.preventDefault()}
                    className="truncate text-xs font-medium text-foreground hover:underline"
                    title={experiment.name}
                >
                    {experiment.name}
                </LinkPrimitive>
                {experiment.noCode && <Badge>No-code</Badge>}
                {experiment.legacy && (
                    <Tooltip>
                        <TooltipTrigger render={<span tabIndex={0} />}>
                            <Badge variant="warning">Legacy</Badge>
                        </TooltipTrigger>
                        <TooltipContent>
                            This experiment uses the legacy engine, so its results are no longer available.
                        </TooltipContent>
                    </Tooltip>
                )}
                {experiment.shippedVariant && (
                    <Tooltip>
                        <TooltipTrigger render={<span tabIndex={0} />}>
                            <Badge variant="completed">100% rollout</Badge>
                        </TooltipTrigger>
                        <TooltipContent>{`Variant "${experiment.shippedVariant}" is rolled out to 100% of users`}</TooltipContent>
                    </Tooltip>
                )}
            </div>
            {experiment.description && (
                <Text size="xs" variant="muted" className="line-clamp-2">
                    {experiment.description}
                </Text>
            )}
        </div>
    )
}

function useColumns(): ColumnDef<ListExperiment>[] {
    return useMemo<ColumnDef<ListExperiment>[]>(
        () => [
            {
                id: 'name',
                header: 'Name',
                meta: { expand: true },
                cell: ({ row }) => <NameCell experiment={row.original} />,
            },
            {
                id: 'tags',
                header: 'Tags',
                enableSorting: false,
                cell: ({ row }) => {
                    const tags = row.original.tags
                    return (
                        <div className="flex items-center gap-1">
                            {tags.slice(0, VISIBLE_TAGS).map((tag) => (
                                <Badge key={tag} className="max-w-24 truncate">
                                    {tag}
                                </Badge>
                            ))}
                            {tags.length > VISIBLE_TAGS && (
                                <Text size="xs" variant="muted" title={tags.slice(VISIBLE_TAGS).join(', ')}>
                                    {`+${tags.length - VISIBLE_TAGS}`}
                                </Text>
                            )}
                        </div>
                    )
                },
            },
            {
                id: 'created_by',
                header: 'Created by',
                enableSorting: false,
                cell: ({ row }) => (
                    <span className="flex items-center gap-1.5 whitespace-nowrap">
                        <Avatar size="xs">
                            <AvatarFallback>{initials(row.original.createdBy)}</AvatarFallback>
                        </Avatar>
                        <Text size="xs">{row.original.createdBy}</Text>
                    </span>
                ),
            },
            {
                id: 'created_at',
                header: 'Created',
                sortDescFirst: true,
                cell: ({ row }) => (
                    <Text size="xs" variant="muted" className="whitespace-nowrap" render={<span />}>
                        <TZLabel time={row.original.createdAt} />
                    </Text>
                ),
            },
            {
                id: 'start_date',
                header: 'Started',
                sortDescFirst: true,
                cell: ({ row }) =>
                    row.original.startDate ? (
                        <Text size="xs" variant="muted" className="whitespace-nowrap" render={<span />}>
                            <TZLabel time={row.original.startDate} />
                        </Text>
                    ) : (
                        <Text size="xs" variant="muted">
                            –
                        </Text>
                    ),
            },
            {
                id: 'duration',
                header: 'Duration',
                sortDescFirst: true,
                meta: { align: 'right' },
                cell: ({ row }) => {
                    const days = duration(row.original)
                    return (
                        <Text
                            size="xs"
                            variant={days === null ? 'muted' : 'default'}
                            className="whitespace-nowrap tabular-nums"
                        >
                            {days === null ? '–' : `${days} ${days === 1 ? 'day' : 'days'}`}
                        </Text>
                    )
                },
            },
            {
                id: 'remaining',
                header: 'Remaining',
                enableSorting: false,
                cell: ({ row }) => <RemainingCell experiment={row.original} />,
            },
            {
                id: 'status',
                header: 'Status',
                cell: ({ row }) => (
                    <Badge variant={STATUS_BADGE[row.original.status]} className="whitespace-nowrap">
                        {STATUS_LABEL[row.original.status]}
                    </Badge>
                ),
            },
            {
                id: 'conclusion',
                header: 'Result',
                enableSorting: false,
                cell: ({ row }) => {
                    const { conclusion, conclusionComment } = row.original
                    if (!conclusion) {
                        return (
                            <Text size="xs" variant="muted">
                                –
                            </Text>
                        )
                    }
                    return (
                        <Tooltip>
                            <TooltipTrigger
                                render={<span tabIndex={0} className="flex items-center gap-1.5 whitespace-nowrap" />}
                            >
                                <Dot variant={CONCLUSION_DOT[conclusion]} />
                                <Text size="xs" weight="medium" render={<span />}>
                                    {CONCLUSION_LABEL[conclusion]}
                                </Text>
                            </TooltipTrigger>
                            <TooltipContent>
                                {conclusionComment ??
                                    `The experiment ended as ${CONCLUSION_LABEL[conclusion].toLowerCase()}.`}
                            </TooltipContent>
                        </Tooltip>
                    )
                },
            },
            {
                id: 'actions',
                header: '',
                enableSorting: false,
                meta: { align: 'right' },
                cell: ({ row }) => <RowActions experiment={row.original} />,
            },
        ],
        []
    )
}

function BulkBar({ selected, total, onClear }: { selected: number; total: number; onClear: () => void }): JSX.Element {
    return (
        <div className="flex items-center gap-2" data-attr="experiments-bulk-bar">
            <Text size="xs" weight="medium">{`${selected} selected`}</Text>
            {selected < total && (
                <Button size="xs" variant="outline">
                    {`Select all ${total} matching`}
                </Button>
            )}
            <Button
                size="xs"
                variant="outline"
                onClick={() => toast({ title: 'Tags updated', description: `${selected} experiments changed.` })}
            >
                Update tags
            </Button>
            <Button size="xs" onClick={onClear}>
                Clear selection
            </Button>
        </div>
    )
}

function ListView({
    rows,
    sorting,
    onSortingChange,
}: {
    rows: ListExperiment[]
    sorting: SortingState
    onSortingChange: (sorting: SortingState) => void
}): JSX.Element {
    const allColumns = useColumns()
    const [wrapperRef, width] = useWidth<HTMLDivElement>()
    const columns =
        width && width < NARROW_TABLE_PX
            ? allColumns.filter((column) => !NARROW_HIDDEN_COLUMNS.includes(column.id ?? ''))
            : allColumns
    const [page, setPage] = useState(1)
    const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
    const selected = Object.values(rowSelection).filter(Boolean).length
    const pageRows = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
    return (
        <div ref={wrapperRef} className="flex flex-col gap-2">
            <div className="flex min-h-7 items-center justify-between gap-2">
                <Text size="xs" variant="muted">
                    {`${rows.length ? (page - 1) * PAGE_SIZE + 1 : 0}-${Math.min(page * PAGE_SIZE, rows.length)} of ${rows.length} experiments`}
                </Text>
                {selected > 0 && (
                    <BulkBar selected={selected} total={rows.length} onClear={() => setRowSelection({})} />
                )}
            </div>
            <Card size="sm" flush className="overflow-clip pt-0">
                <DataTable
                    columns={columns}
                    data={pageRows}
                    fullWidth
                    size="sm"
                    stickyHeader="page"
                    selectable
                    rowSelection={rowSelection}
                    onRowSelectionChange={setRowSelection}
                    getRowId={(experiment) => experiment.key}
                    sorting={sorting}
                    onSortingChange={onSortingChange}
                    className="[--quill-table-sticky-bg:var(--card)]"
                    empty={
                        <div className="flex flex-col items-center gap-1 py-10">
                            <IconSearch className="size-5 text-muted-foreground" />
                            <Text size="sm" weight="medium">
                                No experiments match these filters
                            </Text>
                            <Text size="xs" variant="muted">
                                Change the filters or create a new experiment.
                            </Text>
                        </div>
                    }
                />
                {rows.length > PAGE_SIZE && (
                    <QuillTablePagination
                        currentPage={page}
                        pageCount={Math.ceil(rows.length / PAGE_SIZE)}
                        pageSize={PAGE_SIZE}
                        total={rows.length}
                        onPageChange={setPage}
                    />
                )}
            </Card>
        </div>
    )
}

export function QuillPrototypeExperimentsListV12({
    shell,
    view: initialView = LIST_VIEW.list,
    filters: initialFilters = DEFAULT_FILTERS,
    zoom: initialZoom = TIMELINE_ZOOM.quarter,
    group: initialGroup = TIMELINE_GROUP.status,
}: {
    shell: ShellState
    view?: ListView
    filters?: ListFilters
    zoom?: TimelineZoom
    group?: TimelineGroup
}): JSX.Element {
    const [view, setView] = useState<ListView>(initialView)
    const [filters, setFilters] = useState<ListFilters>(initialFilters)
    const [sorting, setSorting] = useState<SortingState>([{ id: 'created_at', desc: true }])
    const [zoom, setZoom] = useState<TimelineZoom>(initialZoom)
    const [group, setGroup] = useState<TimelineGroup>(initialGroup)
    const rows = sortRows(applyFilters(LIST_EXPERIMENTS, filters), sorting)
    const updateFilters = (next: Partial<ListFilters>): void => setFilters((current) => ({ ...current, ...next }))
    const tabs = [
        ['all', 'Experiments'],
        ['shared-metrics', 'Shared metrics'],
        ['holdouts', 'Holdout groups'],
        ['history', 'History'],
        ['settings', 'Settings'],
    ] as const
    return (
        <ToastProvider timeout={20000}>
            <div data-quill className="flex h-screen bg-background text-foreground">
                <FakeShell shell={shell} />
                <main className="@container/main-content flex min-w-0 flex-1 flex-col">
                    <QuillSceneHeader
                        icon={<IconFlask />}
                        title={
                            <Text size="xs" weight="medium" render={<span />}>
                                Experiments
                            </Text>
                        }
                        actions={<SceneActions />}
                    />
                    <div
                        data-attr="prototype-scroll"
                        className="flex flex-1 flex-col gap-3 overflow-y-auto px-4 pb-4 *:shrink-0"
                    >
                        <Tabs defaultValue="all">
                            <TabsList variant="line">
                                {tabs.map(([key, label]) => (
                                    <TabsTrigger key={key} value={key}>
                                        {label}
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                        </Tabs>
                        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                            <div className="flex flex-wrap items-center gap-2">
                                <AnalyticsSearchInput
                                    value={filters.search}
                                    onChange={(search) => updateFilters({ search })}
                                    label="Search experiments"
                                    placeholder="Search by name or flag"
                                    dataAttr="experiments-search"
                                    className="w-64 max-w-full"
                                />
                                <ListFilterMenu filters={filters} onChange={updateFilters} />
                                <ToggleGroup
                                    variant="outline"
                                    size="sm"
                                    value={[view]}
                                    onValueChange={(value: string[]) => value[0] && setView(value[0] as ListView)}
                                    aria-label="View"
                                    data-attr="experiments-view"
                                >
                                    <ToggleGroupItem value={LIST_VIEW.list} aria-label="List">
                                        <IconList />
                                        List
                                    </ToggleGroupItem>
                                    <ToggleGroupItem value={LIST_VIEW.timeline} aria-label="Timeline">
                                        <IconCalendar />
                                        Timeline
                                    </ToggleGroupItem>
                                </ToggleGroup>
                                {view === LIST_VIEW.timeline && (
                                    <TimelineControls
                                        zoom={zoom}
                                        onZoomChange={setZoom}
                                        group={group}
                                        onGroupChange={setGroup}
                                    />
                                )}
                            </div>
                            <VelocityStats />
                        </div>
                        <ActiveFilters filters={filters} onChange={updateFilters} />
                        {view === LIST_VIEW.list ? (
                            <ListView rows={rows} sorting={sorting} onSortingChange={setSorting} />
                        ) : rows.length ? (
                            <PrototypeExperimentsTimeline experiments={rows} zoom={zoom} group={group} />
                        ) : (
                            <Card size="sm" className="items-center py-10">
                                <Text size="sm" weight="medium">
                                    No experiments match these filters
                                </Text>
                            </Card>
                        )}
                    </div>
                </main>
            </div>
        </ToastProvider>
    )
}
