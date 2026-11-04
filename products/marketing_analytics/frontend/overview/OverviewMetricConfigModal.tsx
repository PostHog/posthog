import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonModal } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { MetricSourceBadge } from '../components/MetricSourceBadge'
import {
    MAX_OVERVIEW_METRICS,
    OVERVIEW_METRIC_SOURCES,
    defaultOverviewMetricSelection,
    moveOverviewMetric,
    overviewMetricSource,
    shownOverviewMetrics,
    toggleOverviewMetric,
} from './overviewMetricConfiguration'
import { overviewMetricsLogic } from './overviewMetricsLogic'

export function OverviewMetricConfigModal({
    items,
    viewKey,
}: {
    items: OverviewMetricCardItem[]
    viewKey: string
}): JSX.Element {
    const logic = overviewMetricsLogic({ viewKey })
    const { selection, editorOpen, draftSelection } = useValues(logic)
    const { closeEditor, applySelection, setDraftSelection } = useActions(logic)
    const draft = draftSelection ?? shownOverviewMetrics(items, selection).map((item) => item.key)
    const full = draft.length >= MAX_OVERVIEW_METRICS

    return (
        <LemonModal
            title="Edit top-line metrics"
            isOpen={editorOpen}
            onClose={closeEditor}
            width={600}
            footer={
                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => setDraftSelection(defaultOverviewMetricSelection(items))}
                        data-attr="marketing-metrics-reset"
                    >
                        Reset to defaults
                    </LemonButton>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeEditor}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => applySelection(draft)}
                            disabledReason={draft.length === 0 ? 'Choose at least one metric' : undefined}
                            data-attr="marketing-metrics-apply"
                        >
                            Apply
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <p className="text-secondary">
                Choose up to {MAX_OVERVIEW_METRICS} metrics to show above the chart. Table columns stay unchanged.
            </p>
            <section aria-label="Shown metrics" className="mb-6">
                <h4 className="mb-2">
                    Shown ({draft.length} of {MAX_OVERVIEW_METRICS})
                </h4>
                {draft.length === 0 ? (
                    <p className="text-secondary">No metrics chosen. Pick at least one below.</p>
                ) : (
                    draft.map((key, index) => (
                        <div key={key} className="flex items-center gap-2 border-b py-2">
                            <MetricSourceBadge source={overviewMetricSource(key)} />
                            <span className="min-w-0 flex-1 break-words">{key}</span>
                            {([-1, 1] as const).map((direction) => (
                                <LemonButton
                                    key={direction}
                                    size="small"
                                    icon={direction === -1 ? <IconArrowUp /> : <IconArrowDown />}
                                    aria-label={`Move ${key} ${direction === -1 ? 'up' : 'down'}`}
                                    tooltip={direction === -1 ? 'Move up' : 'Move down'}
                                    disabledReason={
                                        (direction === -1 ? index === 0 : index === draft.length - 1)
                                            ? 'Already at the end'
                                            : undefined
                                    }
                                    onClick={() => setDraftSelection(moveOverviewMetric(draft, key, direction))}
                                />
                            ))}
                        </div>
                    ))
                )}
            </section>
            <div className="flex flex-col gap-6">
                {OVERVIEW_METRIC_SOURCES.map(({ key: source, label }) => {
                    const metrics = items.filter((item) => overviewMetricSource(item.key) === source)
                    return (
                        <section key={source} aria-label={label}>
                            <h4 className="mb-2 flex items-center gap-2">
                                <MetricSourceBadge source={source} />
                                {label}
                            </h4>
                            {metrics.length === 0 ? (
                                <p className="text-secondary">No metrics available from this source.</p>
                            ) : (
                                metrics.map((item) => {
                                    const checked = draft.includes(item.key)
                                    return (
                                        <div key={item.key} className="border-b py-2">
                                            <LemonCheckbox
                                                checked={checked}
                                                label={<span className="break-words">{item.key}</span>}
                                                onChange={() =>
                                                    setDraftSelection(toggleOverviewMetric(draft, item.key))
                                                }
                                                disabledReason={
                                                    !checked && full
                                                        ? `You can show up to ${MAX_OVERVIEW_METRICS} metrics. Remove one to add another.`
                                                        : undefined
                                                }
                                            />
                                        </div>
                                    )
                                })
                            )}
                        </section>
                    )
                })}
            </div>
        </LemonModal>
    )
}
