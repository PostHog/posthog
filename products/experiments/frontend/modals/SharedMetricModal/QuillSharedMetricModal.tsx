import { useState } from 'react'

import { IconInfo, IconPencil, IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    DataTable,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemMedia,
    Skeleton,
    Text,
    Toggle,
} from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { AnalyticsSearchInput } from 'scenes/analytics/AnalyticsSearchInput'
import { formatMetricTypeName } from 'scenes/experiments/MetricsView/shared/utils'
import { SharedMetric } from 'scenes/experiments/SharedMetrics/sharedMetricLogic'
import { urls } from 'scenes/urls'

import { QuillTagsDialog } from 'products/experiments/frontend/components/QuillTagsDialog'

import { NO_COMPATIBLE_SHARED_METRICS, SharedMetricModalModel } from './useSharedMetricModal'

type SharedMetricTable = DataTableProps<SharedMetric, unknown>

function InfoItem({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Item variant="outline" size="sm" tone="info">
            <ItemMedia variant="icon" aria-hidden>
                <IconInfo />
            </ItemMedia>
            <ItemContent className="min-w-0">
                <ItemDescription className="line-clamp-none">{children}</ItemDescription>
            </ItemContent>
        </Item>
    )
}

export function QuillSharedMetricModal({ model }: { model: SharedMetricModalModel }): JSX.Element {
    const {
        isOpen,
        close,
        save,
        saveLabel,
        saveDisabledReason,
        hasAnyCompatibleSharedMetrics,
        alreadyAddedNote,
        alreadyAddedIds,
        displayedMetrics,
        displayedSelectableIds,
        selectedMetricIds,
        setSelectedMetricIds,
        clearSelectedMetricIds,
        selectAllDisplayed,
        searchTerm,
        setSearchTerm,
        availableTags,
        filterTags,
        selectByTag,
        clearFilterTags,
        loading,
        savingTagsMetricId,
        updateSharedMetricTags,
    } = model
    const [tagsMetric, setTagsMetric] = useState<SharedMetric | null>(null)

    const columns: SharedMetricTable['columns'] = [
        {
            id: 'name',
            header: 'Name',
            enableSorting: false,
            cell: ({ row: { original } }) => (
                <span className="flex items-center gap-2 whitespace-nowrap">
                    <Text size="xs" weight="medium" render={<span />}>
                        {original.name}
                    </Text>
                    {alreadyAddedIds.has(original.id) && (
                        <Text size="xs" variant="muted" render={<span />}>
                            (already added)
                        </Text>
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
            cell: ({ row: { original } }) => formatMetricTypeName(original.query.metric_type),
        },
    ]

    return (
        <Dialog open={isOpen} onOpenChange={(open: boolean) => !open && close()}>
            <DialogContent size="wide" className="max-w-3xl" data-attr="experiment-shared-metric-modal">
                <DialogHeader>
                    <DialogTitle>Select one or more shared metrics</DialogTitle>
                </DialogHeader>
                <DialogBody className="flex flex-col gap-3">
                    {hasAnyCompatibleSharedMetrics ? (
                        <>
                            {alreadyAddedNote && <InfoItem>{alreadyAddedNote}</InfoItem>}
                            <AnalyticsSearchInput
                                value={searchTerm}
                                onChange={setSearchTerm}
                                label="Search shared metrics"
                                placeholder="Search shared metrics..."
                                dataAttr="shared-metric-modal-search"
                            />
                            <div className="flex flex-wrap items-center gap-1">
                                <Text size="xs" variant="muted" render={<span className="mr-1" />}>
                                    Quick select:
                                </Text>
                                <Button
                                    variant="outline"
                                    size="sm"
                                    loading={loading}
                                    disabledReason={
                                        displayedSelectableIds.length === 0 ? 'No metrics to select' : undefined
                                    }
                                    onClick={selectAllDisplayed}
                                >
                                    All
                                </Button>
                                {selectedMetricIds.length > 0 && (
                                    <Button variant="outline" size="sm" onClick={clearSelectedMetricIds}>
                                        Clear
                                    </Button>
                                )}
                            </div>
                            {availableTags.length > 0 && (
                                <div className="flex flex-wrap items-center gap-1">
                                    <Text size="xs" variant="muted" render={<span className="mr-1" />}>
                                        Select by tag:
                                    </Text>
                                    {availableTags.map((tag) => (
                                        <Toggle
                                            key={tag}
                                            variant="outline"
                                            size="sm"
                                            pressed={filterTags.includes(tag)}
                                            // Wait for every page so clicking a tag selects all of its metrics.
                                            disabled={loading}
                                            onPressedChange={() => selectByTag(tag)}
                                        >
                                            {tag}
                                        </Toggle>
                                    ))}
                                    {filterTags.length > 0 && (
                                        <Button size="sm" onClick={clearFilterTags}>
                                            Show all
                                        </Button>
                                    )}
                                </div>
                            )}
                            {loading && displayedMetrics.length === 0 ? (
                                <Skeleton className="h-32 w-full" />
                            ) : (
                                <DataTable
                                    columns={columns}
                                    data={displayedMetrics}
                                    fullWidth
                                    size="sm"
                                    selectable
                                    getRowId={(metric) => String(metric.id)}
                                    rowSelection={Object.fromEntries(selectedMetricIds.map((id) => [String(id), true]))}
                                    onRowSelectionChange={(selection) =>
                                        setSelectedMetricIds(
                                            Object.keys(selection)
                                                .filter((id) => selection[id])
                                                .map(Number)
                                        )
                                    }
                                    rowSelectionLabel={(metric) => metric.name}
                                    rowSelectionDisabledReason={(metric) =>
                                        alreadyAddedIds.has(metric.id) ? 'Already in the experiment' : null
                                    }
                                    empty={
                                        <Text size="xs" variant="muted">
                                            {filterTags.length > 0
                                                ? 'No shared metrics match the selected tags.'
                                                : 'No shared metrics match your search.'}
                                        </Text>
                                    }
                                />
                            )}
                            <div className="flex flex-col items-center gap-1">
                                {loading && displayedMetrics.length > 0 && (
                                    <Text size="xs" variant="muted">
                                        Loading all metrics…
                                    </Text>
                                )}
                                <Button
                                    variant="link"
                                    size="sm"
                                    nativeButton={false}
                                    render={
                                        <LinkPrimitive
                                            to={`${urls.experiments()}?tab=shared-metrics`}
                                            target="_blank"
                                        />
                                    }
                                >
                                    See all shared metrics
                                </Button>
                            </div>
                        </>
                    ) : (
                        <InfoItem>
                            {NO_COMPATIBLE_SHARED_METRICS}{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.experimentsSharedMetric('new')} target="_blank" />}
                            >
                                New shared metric
                            </Button>
                        </InfoItem>
                    )}
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={close}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={save} disabledReason={saveDisabledReason}>
                        {saveLabel}
                    </Button>
                </DialogFooter>
            </DialogContent>
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
        </Dialog>
    )
}
