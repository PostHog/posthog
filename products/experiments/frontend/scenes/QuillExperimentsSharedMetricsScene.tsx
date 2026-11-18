import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCopy, IconEllipsis, IconInfo, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    DataTable,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { QuillTimeCell } from 'lib/components/QuillTableCells/QuillTableCells'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsOwner } from 'scenes/analytics/AnalyticsOwner'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { getMetricTag } from 'scenes/experiments/MetricsView/shared/utils'
import {
    DELETE_SHARED_METRIC_TITLE,
    DeleteSharedMetricCopy,
    fetchRunningExperimentsForSharedMetric,
} from 'scenes/experiments/SharedMetrics/deleteSharedMetricDialog'
import { SharedMetric } from 'scenes/experiments/SharedMetrics/sharedMetricLogic'
import { PAGE_SIZE, sharedMetricsLogic } from 'scenes/experiments/SharedMetrics/sharedMetricsLogic'
import { isLegacySharedMetric } from 'scenes/experiments/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'

import { QuillConfirmDialog } from 'products/experiments/frontend/components/QuillConfirmDialog'
import { QuillTagsDialog } from 'products/experiments/frontend/components/QuillTagsDialog'

import {
    LEGACY_SHARED_METRIC_DOCS_URL,
    LEGACY_SHARED_METRIC_DUPLICATE_REASON,
    LEGACY_SHARED_METRIC_HELP,
    SHARED_METRICS_EMPTY,
    SHARED_METRICS_INTRO,
} from './sharedMetricsCopy'

type SharedMetricTable = DataTableProps<SharedMetric, unknown>
type RunningExperiments = Awaited<ReturnType<typeof fetchRunningExperimentsForSharedMetric>>

export function QuillExperimentsSharedMetricsScene(): JSX.Element {
    const { sharedMetrics, sharedMetricsLoading, searchTerm, savingTagsMetricId, count, page } =
        useValues(sharedMetricsLogic)
    const { setSearchTerm, setPage, updateSharedMetricTags, deleteSharedMetric } = useActions(sharedMetricsLogic)
    const { currentProjectId } = useValues(teamLogic)
    const [deleteCheckMetricId, setDeleteCheckMetricId] = useState<number | null>(null)
    const [pendingDelete, setPendingDelete] = useState<{ id: number; running: NonNullable<RunningExperiments> } | null>(
        null
    )
    const [tagsMetric, setTagsMetric] = useState<SharedMetric | null>(null)

    const startDelete = async (sharedMetricId: number): Promise<void> => {
        if (deleteCheckMetricId !== null) {
            return
        }
        setDeleteCheckMetricId(sharedMetricId)
        try {
            const running = await fetchRunningExperimentsForSharedMetric(currentProjectId, sharedMetricId)
            if (running !== null) {
                setPendingDelete({ id: sharedMetricId, running })
            }
        } finally {
            setDeleteCheckMetricId(null)
        }
    }

    const endCount = page * PAGE_SIZE < count ? page * PAGE_SIZE : count

    const columns: SharedMetricTable['columns'] = [
        {
            id: 'name',
            header: 'Name',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <span className="flex items-center gap-1">
                    <Button
                        variant="link-foreground"
                        size="sm"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.experimentsSharedMetric(original.id)} />}
                    >
                        {original.name}
                    </Button>
                    {isLegacySharedMetric(original) && (
                        <Tooltip>
                            <TooltipTrigger render={<Badge variant="warning" tabIndex={0} />}>Legacy</TooltipTrigger>
                            <TooltipContent className="max-w-80">
                                {LEGACY_SHARED_METRIC_HELP}{' '}
                                <LinkPrimitive to={LEGACY_SHARED_METRIC_DOCS_URL} target="_blank">
                                    Read the docs
                                </LinkPrimitive>
                            </TooltipContent>
                        </Tooltip>
                    )}
                </span>
            ),
        },
        {
            id: 'description',
            header: 'Description',
            enableSorting: false,
            meta: { expand: true },
            cell: ({ row: { original } }) => (
                <Text size="xs" variant="muted" render={<span className="line-clamp-2" />}>
                    {original.description}
                </Text>
            ),
        },
        {
            id: 'tags',
            header: 'Tags',
            enableSorting: false,
            cell: ({ row: { original } }) => {
                const tags = original.tags ?? []
                return (
                    <span className="flex flex-wrap items-center gap-1">
                        {tags.map((tag) => (
                            <Badge key={tag}>{tag}</Badge>
                        ))}
                        <Button
                            size="icon-xs"
                            aria-label={tags.length > 0 ? 'Manage tags' : 'Add tags'}
                            tooltip={tags.length > 0 ? 'Manage tags' : 'Add tags'}
                            loading={savingTagsMetricId === original.id}
                            onClick={() => setTagsMetric(original)}
                            data-attr="shared-metrics-row-tags"
                        >
                            {tags.length > 0 ? <IconPencil /> : <IconPlus />}
                        </Button>
                    </span>
                )
            },
        },
        {
            id: 'type',
            header: 'Type',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <Badge>
                    {getMetricTag(original.query as ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery)}
                </Badge>
            ),
        },
        {
            id: 'created_by',
            header: 'Created by',
            enableSorting: false,
            cell: ({ row: { original } }) => <AnalyticsOwner owner={original.created_by ?? null} />,
        },
        {
            id: 'created_at',
            header: 'Created',
            enableSorting: false,
            cell: ({ row: { original } }) => <QuillTimeCell time={original.created_at} />,
        },
        {
            id: 'actions',
            header: '',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon-xs"
                                aria-label={`Actions for ${original.name}`}
                                loading={deleteCheckMetricId === original.id}
                                data-attr="shared-metrics-row-actions"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem
                            onClick={() => router.actions.push(urls.experimentsSharedMetric(original.id))}
                        >
                            <IconPencil />
                            Edit
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            disabledReason={
                                isLegacySharedMetric(original) ? LEGACY_SHARED_METRIC_DUPLICATE_REASON : undefined
                            }
                            onClick={() => router.actions.push(urls.experimentsSharedMetric(original.id, 'duplicate'))}
                        >
                            <IconCopy />
                            Duplicate
                        </DropdownMenuItem>
                        <DropdownMenuItem variant="destructive" onClick={() => void startDelete(original.id)}>
                            <IconTrash />
                            Delete
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4" data-attr="experiments-shared-metrics">
            <Item variant="outline" size="sm" tone="info">
                <ItemMedia variant="icon" aria-hidden>
                    <IconInfo />
                </ItemMedia>
                <ItemContent className="min-w-0">
                    <ItemDescription className="line-clamp-none">{SHARED_METRICS_INTRO}</ItemDescription>
                </ItemContent>
            </Item>
            <div className="flex items-center justify-between gap-2">
                <AnalyticsSearchInput
                    value={searchTerm}
                    onChange={setSearchTerm}
                    label="Search shared metrics"
                    placeholder="Search shared metrics..."
                    dataAttr="shared-metrics-search"
                />
                <Button
                    variant="primary"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.experimentsSharedMetric('new')} />}
                    data-attr="shared-metrics-new"
                >
                    <IconPlus />
                    New shared metric
                </Button>
            </div>
            <Card size="sm" flush className="pt-0">
                {sharedMetricsLoading && sharedMetrics.length === 0 ? (
                    <Skeleton className="m-3 h-32" />
                ) : (
                    <DataTable
                        columns={columns}
                        data={sharedMetrics}
                        fullWidth
                        size="sm"
                        getRowId={(metric) => String(metric.id)}
                        empty={
                            <Text size="xs" variant="muted">
                                {SHARED_METRICS_EMPTY}
                            </Text>
                        }
                    />
                )}
            </Card>
            {count > PAGE_SIZE && (
                <div className="flex items-center justify-end gap-1">
                    <Button
                        variant="outline"
                        disabledReason={page <= 1 ? 'No previous page' : undefined}
                        onClick={() => setPage(page - 1)}
                    >
                        Previous
                    </Button>
                    <Button
                        variant="outline"
                        disabledReason={endCount >= count ? 'No next page' : undefined}
                        onClick={() => setPage(page + 1)}
                    >
                        Next
                    </Button>
                </div>
            )}
            <QuillTagsDialog
                open={!!tagsMetric}
                name={tagsMetric?.name ?? ''}
                tags={tagsMetric?.tags ?? []}
                onClose={() => setTagsMetric(null)}
                onSave={(tags: string[]) => {
                    if (tagsMetric) {
                        updateSharedMetricTags(tagsMetric.id, tags)
                    }
                    setTagsMetric(null)
                }}
            />
            <QuillConfirmDialog
                open={!!pendingDelete}
                onOpenChange={(open) => !open && setPendingDelete(null)}
                title={DELETE_SHARED_METRIC_TITLE}
                description={
                    pendingDelete ? <DeleteSharedMetricCopy runningExperiments={pendingDelete.running} /> : null
                }
                confirmLabel="Delete"
                destructive
                onConfirm={() => pendingDelete && deleteSharedMetric(pendingDelete.id)}
                dataAttr="shared-metrics-delete-confirm"
            />
        </div>
    )
}
