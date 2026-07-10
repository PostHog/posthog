import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

import type { MetricsViewApi } from 'products/metrics/frontend/generated/api.schemas'

import type { MetricsViewerSavedFilters } from '../metricsViewerState'
import { metricsViewsListLogic } from './metricsViewsListLogic'
import { metricsViewsLogic } from './metricsViewsLogic'

function filterGroupKeys(group: UniversalFiltersGroup): string[] {
    // `filters` is a free-form persisted blob, so a saved view may contain a malformed
    // group (e.g. a nested group missing `values`). Guard against it rather than throwing
    // and crashing the shared views list for everyone on the team.
    if (!group || !Array.isArray(group.values)) {
        return []
    }
    return group.values.flatMap((value: UniversalFiltersGroupValue) =>
        isUniversalGroupFilterLike(value)
            ? filterGroupKeys(value)
            : value && 'key' in value && value.key
              ? [String(value.key)]
              : []
    )
}

function getFiltersSummaryLines(filters: MetricsViewerSavedFilters): { label: string; value: string }[] {
    const lines: { label: string; value: string }[] = []
    if (filters.metricName) {
        lines.push({ label: 'Metric', value: filters.metricName })
    }
    if (filters.aggregation) {
        lines.push({ label: 'Aggregation', value: filters.aggregation })
    }
    if (filters.dateFrom || filters.dateTo) {
        lines.push({ label: 'Date range', value: `${filters.dateFrom ?? ''} → ${filters.dateTo ?? 'now'}` })
    }
    const filterKeys = filters.filters ? filterGroupKeys(filters.filters) : []
    if (filterKeys.length) {
        lines.push({ label: 'Filters', value: filterKeys.join(', ') })
    }
    if (filters.groupBy?.length) {
        lines.push({ label: 'Group by', value: filters.groupBy.join(', ') })
    }
    if (filters.viewMode) {
        lines.push({ label: 'View', value: filters.viewMode })
    }
    return lines
}

function FiltersSummaryDisplay({ filters }: { filters: MetricsViewerSavedFilters }): JSX.Element {
    const lines = getFiltersSummaryLines(filters)
    if (lines.length === 0) {
        return <span className="text-muted text-xs">No filters</span>
    }
    return (
        <div className="text-xs text-muted space-y-0.5">
            {lines.map((line) => (
                <div key={line.label}>
                    <span className="font-medium">{line.label}:</span> {line.value}
                </div>
            ))}
        </div>
    )
}

function SaveViewModal(): JSX.Element | null {
    const { isSaveModalOpen, viewName, savedFilters, viewsLoading } = useValues(metricsViewsListLogic)
    const { closeSaveModal, setViewName, saveView } = useActions(metricsViewsListLogic)
    const shouldRender = useKeepMountedWhileOpen(isSaveModalOpen)

    if (!shouldRender) {
        return null
    }

    return (
        <LemonModal
            isOpen={isSaveModalOpen}
            onClose={closeSaveModal}
            title="Save current view"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSaveModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveView}
                        loading={viewsLoading}
                        disabledReason={!viewName.trim() ? 'Enter a name' : viewsLoading ? 'Saving…' : undefined}
                    >
                        Save view
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <LemonInput
                    placeholder="View name"
                    value={viewName}
                    onChange={setViewName}
                    autoFocus
                    onPressEnter={saveView}
                />
                <FiltersSummaryDisplay filters={savedFilters} />
            </div>
        </LemonModal>
    )
}

export function SavedViewsModal(): JSX.Element {
    const { isModalOpen } = useValues(metricsViewsListLogic)
    const { closeModal, openSaveModal } = useActions(metricsViewsListLogic)
    const { views, viewsLoading } = useValues(metricsViewsLogic)
    const { deleteView, loadView } = useActions(metricsViewsLogic)
    const shouldRenderList = useKeepMountedWhileOpen(isModalOpen)

    const columns: LemonTableColumns<MetricsViewApi> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, view) => <span className="font-medium">{view.name}</span>,
        },
        {
            title: 'Filters',
            render: (_, view) => <FiltersSummaryDisplay filters={(view.filters ?? {}) as MetricsViewerSavedFilters} />,
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: (_, view) => (
                <span className="text-muted text-xs">
                    {view.created_by?.first_name || view.created_by?.email || '—'}
                </span>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (_, view) => <TZLabel time={view.created_at} />,
        },
        {
            title: '',
            render: (_, view) => (
                <div className="flex items-center gap-1">
                    <LemonButton type="secondary" size="xsmall" onClick={() => loadView(view)}>
                        Load
                    </LemonButton>
                    <More
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: 'Delete',
                                        status: 'danger',
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: `Delete "${view.name}"?`,
                                                description:
                                                    'This view will be permanently deleted. This action cannot be undone.',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    type: 'primary',
                                                    status: 'danger',
                                                    onClick: () => deleteView(view.short_id),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        },
                                    },
                                ]}
                            />
                        }
                    />
                </div>
            ),
        },
    ]

    return (
        <>
            {shouldRenderList && (
                <LemonModal
                    isOpen={isModalOpen}
                    onClose={closeModal}
                    title="Saved views"
                    width={720}
                    footer={
                        <div className="flex justify-between w-full">
                            <LemonButton type="primary" onClick={openSaveModal}>
                                Save current view
                            </LemonButton>
                            <LemonButton type="secondary" onClick={closeModal}>
                                Close
                            </LemonButton>
                        </div>
                    }
                >
                    <LemonTable
                        columns={columns}
                        dataSource={views}
                        rowKey="id"
                        loading={viewsLoading}
                        emptyState="No saved views yet."
                        size="small"
                    />
                </LemonModal>
            )}
            <SaveViewModal />
        </>
    )
}
