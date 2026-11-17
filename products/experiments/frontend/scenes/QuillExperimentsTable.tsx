import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { type ReactNode, useEffect, useState } from 'react'

import { IconEllipsis, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    DataTable,
    Dot,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Progress,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
    cn,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { BulkUpdateTagsButton } from 'lib/components/BulkActions/BulkUpdateTagsButton'
import { QuillEmptyCell, QuillTimeCell } from 'lib/components/QuillTableCells/QuillTableCells'
import { QuillTablePagination } from 'lib/components/QuillTablePagination/QuillTablePagination'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Link, LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { pluralize } from 'lib/utils/strings'
import { AnalyticsOwner } from 'scenes/analytics/AnalyticsOwner'
import { AnalyticsTagIcon } from 'scenes/analytics/AnalyticsTagIcon'
import { ROW_HOVER_REVEAL } from 'scenes/analytics/analyticsUtils'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import {
    AccessControlLevel,
    AccessControlResourceType,
    Experiment,
    ExperimentConclusion,
    ExperimentStatus,
} from '~/types'

import { CONCLUSION_DISPLAY_CONFIG } from 'products/experiments/frontend/constants'
import {
    canArchiveExperiment,
    confirmArchiveExperiment,
    confirmDeleteExperiment,
} from 'products/experiments/frontend/experimentActions'
import { getExperimentStatus } from 'products/experiments/frontend/experimentStatus'
import {
    EXPERIMENTS_PER_PAGE,
    experimentsLogic,
    getExperimentStatusLabel,
    getShippedVariantKey,
    isSingleVariantShipped,
} from 'products/experiments/frontend/scenes/experimentsLogic'

import {
    EXPERIMENTS_TABLE_EMPTY,
    LEGACY_EXPERIMENT_DOCS,
    LEGACY_EXPERIMENT_TOOLTIP,
    type MatchingExperimentIds,
    copyExperimentDisabledReason,
    duplicateExperimentDisabledReason,
    experimentSelectionDisabledReason,
    formatExperimentDuration,
    getExperimentDuration,
    getExperimentConclusionTooltip,
    getExperimentRemainingTime,
    startExperimentSurvey,
} from './experimentsTable'
import { QuillExperimentTagsDialog } from './QuillExperimentTagsDialog'

type ExperimentsDataTable = DataTableProps<Experiment, unknown>
type SortingState = NonNullable<ExperimentsDataTable['sorting']>
type RowSelectionState = NonNullable<ExperimentsDataTable['rowSelection']>

type BadgeVariant = 'default' | 'info' | 'warning' | 'success' | 'completed' | 'destructive'

const STATUS_BADGE: Record<ExperimentStatus, BadgeVariant> = {
    [ExperimentStatus.Draft]: 'default',
    [ExperimentStatus.Running]: 'success',
    [ExperimentStatus.Paused]: 'warning',
    [ExperimentStatus.ExposureFrozen]: 'info',
    [ExperimentStatus.Stopped]: 'completed',
}

const CONCLUSION_DOT: Partial<Record<ExperimentConclusion, 'success' | 'destructive' | 'warning'>> = {
    [ExperimentConclusion.Won]: 'success',
    [ExperimentConclusion.Lost]: 'destructive',
    [ExperimentConclusion.Inconclusive]: 'warning',
}

const SORTABLE_ORDER_KEYS = new Set(['created_by', 'created_at', 'start_date', 'duration', 'status', 'conclusion'])

function sortingFromOrder(order: string | undefined): SortingState {
    const value = order ?? '-created_at'
    return [{ id: value.replace(/^-/, ''), desc: value.startsWith('-') }]
}

function BadgeWithTooltip({
    variant,
    tooltip,
    children,
}: {
    variant: BadgeVariant
    tooltip: ReactNode
    children: ReactNode
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<Badge variant={variant} tabIndex={0} />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

function TagsCell({
    experiment,
    onManageTags,
}: {
    experiment: Experiment
    onManageTags: (experiment: Experiment) => void
}): JSX.Element {
    const { filters } = useValues(experimentsLogic)
    const { setExperimentsFilters } = useActions(experimentsLogic)
    const tags = experiment.tags ?? []
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Experiment,
        AccessControlLevel.Editor,
        experiment.user_access_level
    )

    if (!tags.length) {
        return editDisabledReason ? (
            <QuillEmptyCell />
        ) : (
            <Button
                size="icon-xs"
                tooltip="Add tags"
                aria-label={`Add tags to ${experiment.name}`}
                className={ROW_HOVER_REVEAL}
                onClick={() => onManageTags(experiment)}
                data-attr="experiments-list-row-tags-add"
            >
                <IconPlus />
            </Button>
        )
    }

    const activeTags = filters.tags ?? []
    const filtered = tags.find((tag) => activeTags.includes(tag))
    const toggle = (tag: string): void => {
        const next = activeTags.includes(tag) ? activeTags.filter((other) => other !== tag) : [...activeTags, tag]
        setExperimentsFilters({ tags: next.length > 0 ? next : undefined, page: 1 })
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="outline"
                        size="xs"
                        aria-label={pluralize(tags.length, 'tag')}
                        className="max-w-48 shrink-0 gap-1 px-1.5"
                        data-attr="experiments-list-row-tags"
                    />
                }
            >
                <AnalyticsTagIcon />
                {filtered ? (
                    <>
                        <span className="min-w-0 truncate">{filtered}</span>
                        {tags.length > 1 && (
                            <span className="shrink-0 text-muted-foreground">{`+${tags.length - 1}`}</span>
                        )}
                    </>
                ) : (
                    <span>{tags.length}</span>
                )}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56 max-w-80">
                <DropdownMenuGroup>
                    <div className="flex items-center justify-between gap-2">
                        <DropdownMenuLabel>{pluralize(tags.length, 'tag')}</DropdownMenuLabel>
                        <DropdownMenuItem
                            className="w-auto shrink-0"
                            disabledReason={editDisabledReason ?? undefined}
                            onClick={() => onManageTags(experiment)}
                            data-attr="experiments-list-row-tags-manage"
                        >
                            Manage
                        </DropdownMenuItem>
                    </div>
                    {tags.map((tag) => {
                        const active = activeTags.includes(tag)
                        return (
                            <DropdownMenuItem
                                key={tag}
                                onClick={() => toggle(tag)}
                                data-attr="experiments-list-row-tag"
                            >
                                <AnalyticsTagIcon className="size-3.5" />
                                <span className="min-w-0 flex-1 break-all text-left">{tag}</span>
                                <Text size="xs" variant="muted" className="ml-2 shrink-0">
                                    {active ? 'Remove filter' : 'Filter'}
                                </Text>
                            </DropdownMenuItem>
                        )
                    })}
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function NameCell({ experiment }: { experiment: Experiment }): JSX.Element {
    return (
        <>
            <Button
                variant="link-foreground"
                size="sm"
                nativeButton={false}
                className="ph-no-capture"
                render={<LinkPrimitive to={experiment.id ? urls.experiment(experiment.id) : undefined} />}
            >
                {experiment.name}
            </Button>
            <span className="inline-flex flex-wrap items-center gap-1 align-middle">
                {experiment.type === 'web' && <Badge>No-code</Badge>}
                {experiment.is_legacy && (
                    <BadgeWithTooltip
                        variant="warning"
                        tooltip={
                            <span className="flex flex-col gap-1">
                                <span>{LEGACY_EXPERIMENT_TOOLTIP}</span>
                                <Link
                                    to={LEGACY_EXPERIMENT_DOCS}
                                    target="_blank"
                                    className="text-primary-on-foreground underline"
                                >
                                    Read the docs
                                </Link>
                            </span>
                        }
                    >
                        Legacy
                    </BadgeWithTooltip>
                )}
                {isSingleVariantShipped(experiment) && (
                    <BadgeWithTooltip
                        variant="completed"
                        tooltip={`Variant "${getShippedVariantKey(experiment)}" has been rolled out to 100% of users`}
                    >
                        100% rollout
                    </BadgeWithTooltip>
                )}
            </span>
            {experiment.description && (
                <div className="pb-1">
                    <LemonMarkdown
                        className="ph-no-capture max-w-120 line-clamp-2 text-xs text-muted-foreground"
                        lowKeyHeadings
                        disableImages
                    >
                        {experiment.description}
                    </LemonMarkdown>
                </div>
            )}
        </>
    )
}

function RemainingCell({ experiment }: { experiment: Experiment }): JSX.Element {
    const remaining = getExperimentRemainingTime(experiment)
    return (
        <Tooltip>
            <TooltipTrigger render={<div className="w-20" tabIndex={0} />}>
                <Progress
                    value={remaining.percent}
                    variant={remaining.state === 'done' ? 'success' : 'default'}
                    aria-label={remaining.tooltip}
                />
            </TooltipTrigger>
            <TooltipContent>{remaining.tooltip}</TooltipContent>
        </Tooltip>
    )
}

function ResultCell({ experiment }: { experiment: Experiment }): JSX.Element {
    if (!experiment.conclusion) {
        return <QuillEmptyCell />
    }
    const config = CONCLUSION_DISPLAY_CONFIG[experiment.conclusion]
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="flex items-center gap-2" tabIndex={0} />}>
                <Dot variant={CONCLUSION_DOT[experiment.conclusion] ?? 'default'} />
                <Text size="xs" weight="medium" render={<span />}>
                    {config.title}
                </Text>
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{getExperimentConclusionTooltip(experiment)}</TooltipContent>
        </Tooltip>
    )
}

interface ExperimentsTableActions {
    openDuplicateModal: (experiment: Experiment) => void
    openSurveyModal: (experiment: Experiment) => void
    openCopyToProjectModal: (experiment: Experiment) => void
}

function ActionsCell({
    experiment,
    hasMultipleProjects,
    openDuplicateModal,
    openSurveyModal,
    openCopyToProjectModal,
}: ExperimentsTableActions & { experiment: Experiment; hasMultipleProjects: boolean }): JSX.Element {
    const { currentProjectId } = useValues(experimentsLogic)
    const { loadExperiments, archiveExperiment, unarchiveExperiment } = useActions(experimentsLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon-sm"
                        aria-label={`Actions for ${experiment.name}`}
                        data-attr="experiments-list-row-menu"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
                <DropdownMenuGroup>
                    <DropdownMenuItem onClick={() => router.actions.push(urls.experiment(`${experiment.id}`))}>
                        View
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        disabledReason={duplicateExperimentDisabledReason(experiment)}
                        onClick={() => openDuplicateModal(experiment)}
                    >
                        Duplicate
                    </DropdownMenuItem>
                    {hasMultipleProjects && (
                        <DropdownMenuItem
                            disabledReason={copyExperimentDisabledReason(experiment)}
                            onClick={() => openCopyToProjectModal(experiment)}
                        >
                            Copy to project
                        </DropdownMenuItem>
                    )}
                    {experiment.feature_flag && (
                        <DropdownMenuItem
                            data-attr="create-survey"
                            onClick={() => startExperimentSurvey(experiment, openSurveyModal)}
                        >
                            Create survey
                        </DropdownMenuItem>
                    )}
                    {canArchiveExperiment(experiment) && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Experiment}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={experiment.user_access_level}
                        >
                            <DropdownMenuItem
                                data-attr={`experiment-${experiment.id}-dropdown-archive`}
                                onClick={() =>
                                    confirmArchiveExperiment(experiment, (disableFlag) =>
                                        archiveExperiment({
                                            id: experiment.id as number,
                                            disableFeatureFlag: disableFlag,
                                        })
                                    )
                                }
                            >
                                Archive experiment
                            </DropdownMenuItem>
                        </AccessControlAction>
                    )}
                    {experiment.archived && (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Experiment}
                            minAccessLevel={AccessControlLevel.Editor}
                            userAccessLevel={experiment.user_access_level}
                        >
                            <DropdownMenuItem
                                data-attr={`experiment-${experiment.id}-dropdown-unarchive`}
                                onClick={() => unarchiveExperiment(experiment.id as number)}
                            >
                                Unarchive experiment
                            </DropdownMenuItem>
                        </AccessControlAction>
                    )}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <AccessControlAction
                        resourceType={AccessControlResourceType.Experiment}
                        minAccessLevel={AccessControlLevel.Editor}
                        userAccessLevel={experiment.user_access_level}
                    >
                        <DropdownMenuItem
                            variant="destructive"
                            data-attr={`experiment-${experiment.id}-dropdown-remove`}
                            onClick={() =>
                                confirmDeleteExperiment({
                                    projectId: currentProjectId,
                                    experiment,
                                    onDelete: () => loadExperiments(),
                                })
                            }
                        >
                            Delete experiment
                        </DropdownMenuItem>
                    </AccessControlAction>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function experimentColumns({
    onManageTags,
    ...actions
}: ExperimentsTableActions & {
    hasMultipleProjects: boolean
    onManageTags: (experiment: Experiment) => void
}): ExperimentsDataTable['columns'] {
    return [
        {
            id: 'name',
            header: 'Name',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row }) => <NameCell experiment={row.original} />,
        },
        {
            id: 'tags',
            header: 'Tags',
            enableSorting: false,
            cell: ({ row }) => <TagsCell experiment={row.original} onManageTags={onManageTags} />,
        },
        {
            id: 'created_by',
            header: 'Owner',
            accessorFn: (experiment) => experiment.created_by?.first_name ?? '',
            cell: ({ row }) => <AnalyticsOwner owner={row.original.created_by ?? null} />,
        },
        {
            id: 'created_at',
            header: 'Created',
            accessorFn: (experiment) => experiment.created_at,
            cell: ({ row }) => <QuillTimeCell time={row.original.created_at} />,
        },
        {
            id: 'start_date',
            header: 'Started',
            accessorFn: (experiment) => experiment.start_date,
            cell: ({ row }) => <QuillTimeCell time={row.original.start_date} />,
        },
        {
            id: 'duration',
            header: 'Duration',
            meta: { align: 'right' },
            accessorFn: (experiment) => getExperimentDuration(experiment) ?? -1,
            cell: ({ row }) =>
                getExperimentDuration(row.original) === undefined ? (
                    <QuillEmptyCell />
                ) : (
                    <Text size="xs" render={<span />}>
                        {formatExperimentDuration(row.original)}
                    </Text>
                ),
        },
        {
            id: 'remaining_time',
            header: 'Remaining',
            enableSorting: false,
            cell: ({ row }) => <RemainingCell experiment={row.original} />,
        },
        {
            id: 'status',
            header: 'Status',
            accessorFn: (experiment) => getExperimentStatus(experiment),
            cell: ({ row }) => {
                const status = getExperimentStatus(row.original)
                return <Badge variant={STATUS_BADGE[status]}>{getExperimentStatusLabel(status)}</Badge>
            },
        },
        {
            id: 'conclusion',
            header: 'Result',
            accessorFn: (experiment) => experiment.conclusion ?? '',
            cell: ({ row }) => <ResultCell experiment={row.original} />,
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            meta: { align: 'right' },
            cell: ({ row }) => <ActionsCell experiment={row.original} {...actions} />,
        },
    ]
}

export function QuillExperimentsTable({
    matching,
    openDuplicateModal,
    openSurveyModal,
    openCopyToProjectModal,
}: ExperimentsTableActions & { matching: MatchingExperimentIds }): JSX.Element {
    const { experiments, experimentsLoading, filters, count } = useValues(experimentsLogic)
    const { loadExperiments, setExperimentsFilters } = useActions(experimentsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const hasMultipleProjects = (currentOrganization?.projects?.length ?? 0) > 1
    const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
    const [tagsExperiment, setTagsExperiment] = useState<Experiment | null>(null)

    useEffect(() => {
        setRowSelection({})
    }, [matching.filterIdentity])

    const page = filters.page || 1
    const startCount = count === 0 ? 0 : (page - 1) * EXPERIMENTS_PER_PAGE + 1
    const endCount = page * EXPERIMENTS_PER_PAGE < count ? page * EXPERIMENTS_PER_PAGE : count
    const selectedIds = Object.keys(rowSelection)
        .filter((id) => rowSelection[id])
        .map(Number)
    const selectedIdSet = new Set(selectedIds)
    const isAllMatchingSelected =
        matching.matchingExperimentIds !== null &&
        selectedIds.length === matching.matchingExperimentIds.length &&
        matching.matchingExperimentIds.every((id) => selectedIdSet.has(id))
    const showSelectAllMatching =
        !isAllMatchingSelected && selectedIds.length >= EXPERIMENTS_PER_PAGE && count > selectedIds.length

    return (
        <div className="flex flex-col gap-2" data-attr="experiments-table-container">
            {count ? (
                <div className="flex min-h-9 items-center justify-between gap-2" data-attr="experiments-count-row">
                    <Text size="xs" variant="muted" render={<span />}>
                        {`${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${pluralize(count, 'experiment')}`}
                    </Text>
                    {selectedIds.length > 0 && (
                        <div className="flex items-center gap-2" data-attr="experiments-selection-bar">
                            <Text size="xs" variant="muted" render={<span />}>
                                {isAllMatchingSelected
                                    ? `All ${selectedIds.length} matching experiments selected`
                                    : `${pluralize(selectedIds.length, 'experiment')} selected`}
                            </Text>
                            {showSelectAllMatching && (
                                <Button
                                    variant="outline"
                                    loading={matching.matchingExperimentIdsLoading}
                                    onClick={() =>
                                        void matching.selectAllMatching((ids) =>
                                            setRowSelection(Object.fromEntries(ids.map((id) => [String(id), true])))
                                        )
                                    }
                                >
                                    Select all {count} matching experiments
                                </Button>
                            )}
                            <BulkUpdateTagsButton
                                resource="experiments"
                                selectedIds={selectedIds}
                                onSuccess={() => {
                                    setRowSelection({})
                                    matching.clearMatchingExperimentIds()
                                    loadExperiments()
                                }}
                            />
                            <Button variant="link" onClick={() => setRowSelection({})}>
                                Clear
                            </Button>
                        </div>
                    )}
                </div>
            ) : null}
            <Card size="sm" flush className="pt-0" data-attr="experiment-table">
                <div
                    className={cn('transition-opacity', experimentsLoading && 'opacity-60')}
                    aria-busy={experimentsLoading}
                >
                    <DataTable
                        columns={experimentColumns({
                            hasMultipleProjects,
                            onManageTags: setTagsExperiment,
                            openDuplicateModal,
                            openSurveyModal,
                            openCopyToProjectModal,
                        })}
                        data={experiments.results}
                        fullWidth
                        size="sm"
                        rowClassName={() => 'group/row'}
                        sorting={sortingFromOrder(filters.order)}
                        onSortingChange={([sort]) => {
                            if (sort && SORTABLE_ORDER_KEYS.has(sort.id)) {
                                setExperimentsFilters({ order: `${sort.desc ? '-' : ''}${sort.id}`, page: 1 })
                            }
                        }}
                        selectable
                        rowSelection={rowSelection}
                        onRowSelectionChange={setRowSelection}
                        getRowId={(experiment) => String(experiment.id)}
                        rowSelectionLabel={(experiment) => `Select experiment ${experiment.name}`}
                        rowSelectionDisabledReason={experimentSelectionDisabledReason}
                        empty={
                            <Text size="xs" variant="muted">
                                {EXPERIMENTS_TABLE_EMPTY}
                            </Text>
                        }
                    />
                </div>
                {count > EXPERIMENTS_PER_PAGE && (
                    <QuillTablePagination
                        currentPage={page}
                        pageCount={Math.ceil(count / EXPERIMENTS_PER_PAGE)}
                        pageSize={EXPERIMENTS_PER_PAGE}
                        total={count}
                        onPageChange={(nextPage) => setExperimentsFilters({ page: nextPage })}
                    />
                )}
            </Card>
            <QuillExperimentTagsDialog
                experiment={tagsExperiment}
                onClose={() => setTagsExperiment(null)}
                onSaved={() => {
                    setTagsExperiment(null)
                    loadExperiments()
                }}
            />
        </div>
    )
}
