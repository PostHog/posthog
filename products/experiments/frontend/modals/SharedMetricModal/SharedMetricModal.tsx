import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonModal, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { formatMetricTypeName } from 'scenes/experiments/MetricsView/shared/utils'
import { InlineTagEditor } from 'scenes/experiments/SharedMetrics/InlineTagEditor'
import { SharedMetric } from 'scenes/experiments/SharedMetrics/sharedMetricLogic'
import { urls } from 'scenes/urls'

import { Experiment } from '~/types'

import { MetricContext } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'

import { QuillSharedMetricModal } from './QuillSharedMetricModal'
import { NO_COMPATIBLE_SHARED_METRICS, useSharedMetricModal } from './useSharedMetricModal'

export function SharedMetricModal({
    experiment,
    onSave,
}: {
    experiment: Experiment
    onSave: (metrics: SharedMetric[], context: MetricContext) => void
}): JSX.Element | null {
    const model = useSharedMetricModal(experiment, onSave)
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!model.ready) {
        return null
    }

    if (todayRailNav && resultsRedesign) {
        return <QuillSharedMetricModal model={model} />
    }

    const {
        isOpen: isModalOpen,
        close: closeModal,
        save,
        saveLabel,
        saveDisabledReason,
        hasAnyCompatibleSharedMetrics,
        alreadyAddedNote,
        alreadyAddedIds,
        displayedMetrics,
        displayedSelectableIds,
        selectedMetricIds,
        toggleSelectedMetricId,
        clearSelectedMetricIds,
        selectAllDisplayed,
        searchTerm,
        setSearchTerm,
        availableTags,
        filterTags,
        selectByTag,
        clearFilterTags,
        loading: sharedMetricsResponseLoading,
        savingTagsMetricId,
        updateSharedMetricTags,
    } = model

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeModal}
            maxWidth={800}
            title="Select one or more shared metrics"
            footer={
                <div className="flex justify-between w-full">
                    <div className="flex gap-2">
                        <LemonButton onClick={closeModal} type="secondary">
                            Cancel
                        </LemonButton>
                        {/* Changing the existing metric is a pain because saved metrics are stored separately */}
                        {/* Only allow deletion for now */}
                        <LemonButton onClick={save} type="primary" disabledReason={saveDisabledReason}>
                            {saveLabel}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="deprecated-space-y-2">
                {hasAnyCompatibleSharedMetrics ? (
                    <>
                        {alreadyAddedNote && <LemonBanner type="info">{alreadyAddedNote}</LemonBanner>}
                        <LemonInput
                            type="search"
                            placeholder="Search shared metrics..."
                            value={searchTerm}
                            onChange={setSearchTerm}
                            fullWidth
                        />
                        <div className="flex flex-wrap gap-2 items-center">
                            <LemonLabel>Quick select:</LemonLabel>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                loading={sharedMetricsResponseLoading}
                                disabledReason={
                                    displayedSelectableIds.length === 0 ? 'No metrics to select' : undefined
                                }
                                onClick={selectAllDisplayed}
                            >
                                All
                            </LemonButton>
                            {selectedMetricIds.length > 0 && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    onClick={() => {
                                        clearSelectedMetricIds()
                                    }}
                                >
                                    Clear
                                </LemonButton>
                            )}
                        </div>
                        {availableTags.length > 0 && (
                            <div className="flex flex-wrap gap-2 items-center">
                                <LemonLabel>Select by tag:</LemonLabel>
                                {availableTags.map((tag: string) => (
                                    <LemonButton
                                        key={tag}
                                        size="xsmall"
                                        type="secondary"
                                        active={filterTags.includes(tag)}
                                        // Wait for every page so clicking a tag selects all of its metrics.
                                        disabledReason={
                                            sharedMetricsResponseLoading ? 'Loading all metrics…' : undefined
                                        }
                                        onClick={() => selectByTag(tag)}
                                    >
                                        {tag}
                                    </LemonButton>
                                ))}
                                {filterTags.length > 0 && (
                                    <LemonButton size="xsmall" type="tertiary" onClick={() => clearFilterTags()}>
                                        Show all
                                    </LemonButton>
                                )}
                            </div>
                        )}
                        <LemonTable
                            dataSource={displayedMetrics}
                            loading={sharedMetricsResponseLoading && displayedMetrics.length === 0}
                            emptyState={
                                filterTags.length > 0 ? (
                                    <div>No shared metrics match the selected tags.</div>
                                ) : (
                                    <div>No shared metrics match your search.</div>
                                )
                            }
                            columns={[
                                {
                                    title: '',
                                    key: 'checkbox',
                                    render: (_, metric: SharedMetric) => (
                                        <input
                                            type="checkbox"
                                            disabled={alreadyAddedIds.has(metric.id)}
                                            checked={selectedMetricIds.includes(metric.id)}
                                            onChange={() => {
                                                toggleSelectedMetricId(metric.id)
                                            }}
                                        />
                                    ),
                                },
                                {
                                    title: 'Name',
                                    key: 'name',
                                    render: (_, metric: SharedMetric) => (
                                        <span>
                                            {metric.name}
                                            {alreadyAddedIds.has(metric.id) && (
                                                <span className="text-secondary ml-2">(already added)</span>
                                            )}
                                        </span>
                                    ),
                                },
                                {
                                    title: 'Description',
                                    dataIndex: 'description',
                                    key: 'description',
                                },
                                {
                                    title: 'Tags',
                                    dataIndex: 'tags' as keyof SharedMetric,
                                    key: 'tags',
                                    render: (_: any, metric: SharedMetric) => (
                                        <InlineTagEditor
                                            metric={metric}
                                            onSave={(newTags) => updateSharedMetricTags(metric.id, newTags)}
                                            saving={savingTagsMetricId === metric.id}
                                        />
                                    ),
                                },
                                {
                                    title: 'Type',
                                    key: 'type',
                                    render: (_, metric: SharedMetric) => formatMetricTypeName(metric.query.metric_type),
                                },
                            ]}
                            footer={
                                <div className="flex flex-col items-center gap-2 m-2">
                                    {sharedMetricsResponseLoading && displayedMetrics.length > 0 && (
                                        <span className="text-secondary text-xs">Loading all metrics…</span>
                                    )}
                                    <Link to={`${urls.experiments()}?tab=shared-metrics`} target="_blank">
                                        See all shared metrics
                                    </Link>
                                </div>
                            }
                        />
                    </>
                ) : (
                    <LemonBanner className="w-full" type="info">
                        <div className="mb-2">{NO_COMPATIBLE_SHARED_METRICS}</div>
                        <Link to={urls.experimentsSharedMetric('new')} target="_blank">
                            New shared metric
                        </Link>
                    </LemonBanner>
                )}
            </div>
        </LemonModal>
    )
}
