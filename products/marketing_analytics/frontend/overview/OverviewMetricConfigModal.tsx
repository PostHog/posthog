import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonModal } from '@posthog/lemon-ui'

import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import type { OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { OVERVIEW_METRIC_GROUPS, overviewMetricsForGroup } from './overviewMetricConfiguration'
import { overviewMetricsLogic } from './overviewMetricsLogic'

export function OverviewMetricConfigModal({
    items,
    viewKey,
}: {
    items: OverviewMetricCardItem[]
    viewKey: string
}): JSX.Element {
    const logic = overviewMetricsLogic({ viewKey })
    const { configuration, draftConfiguration } = useValues(logic)
    const { closeConfiguration, applyConfiguration, updateDraftGroup, resetDraft } = useActions(logic)

    return (
        <LemonModal
            title="Configure metrics"
            isOpen={!!draftConfiguration}
            onClose={closeConfiguration}
            width={600}
            footer={
                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                    <LemonButton type="secondary" onClick={resetDraft} data-attr="marketing-metrics-reset">
                        Reset to defaults
                    </LemonButton>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeConfiguration}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={() => draftConfiguration && applyConfiguration(draftConfiguration)}
                            disabledReason={
                                JSON.stringify(configuration) === JSON.stringify(draftConfiguration)
                                    ? 'No changes to apply'
                                    : undefined
                            }
                            data-attr="marketing-metrics-apply"
                        >
                            Apply
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <p className="text-secondary">
                Choose which metrics appear in this summary and change their order. Table columns stay unchanged.
            </p>
            <div className="flex flex-col gap-6">
                {draftConfiguration &&
                    OVERVIEW_METRIC_GROUPS.map(({ key: group, label }) => {
                        const metrics = overviewMetricsForGroup(items, group, draftConfiguration)
                        const { hidden } = draftConfiguration[group]
                        return (
                            <section key={group} aria-label={label}>
                                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                                    <h4 className="m-0">{label}</h4>
                                    <div className="flex gap-1">
                                        <LemonButton
                                            size="small"
                                            onClick={() => updateDraftGroup(group, { hidden: [] })}
                                            disabledReason={!hidden.length ? 'All metrics are visible' : undefined}
                                        >
                                            Show all
                                        </LemonButton>
                                        <LemonButton
                                            size="small"
                                            onClick={() =>
                                                updateDraftGroup(group, {
                                                    hidden: [
                                                        ...new Set([...hidden, ...metrics.map((item) => item.key)]),
                                                    ],
                                                })
                                            }
                                            disabledReason={
                                                metrics.every((item) => hidden.includes(item.key))
                                                    ? 'All metrics are hidden'
                                                    : undefined
                                            }
                                        >
                                            Hide all
                                        </LemonButton>
                                    </div>
                                </div>
                                {metrics.length === 0 ? (
                                    <p className="text-secondary">No metrics available for this group.</p>
                                ) : (
                                    metrics.map((item, index) => (
                                        <div key={item.key} className="flex items-center gap-2 border-b py-2">
                                            <LemonCheckbox
                                                className="min-w-0 flex-1"
                                                checked={!hidden.includes(item.key)}
                                                label={<span className="break-words">{item.key}</span>}
                                                onChange={(checked) =>
                                                    updateDraftGroup(group, {
                                                        hidden: checked
                                                            ? hidden.filter((key) => key !== item.key)
                                                            : [...hidden, item.key],
                                                    })
                                                }
                                            />
                                            {([-1, 1] as const).map((direction) => (
                                                <LemonButton
                                                    key={direction}
                                                    size="small"
                                                    icon={direction === -1 ? <IconArrowUp /> : <IconArrowDown />}
                                                    aria-label={`Move ${item.key} ${direction === -1 ? 'up' : 'down'}`}
                                                    tooltip={direction === -1 ? 'Move up' : 'Move down'}
                                                    disabledReason={
                                                        (direction === -1 ? index === 0 : index === metrics.length - 1)
                                                            ? 'Already at the end'
                                                            : undefined
                                                    }
                                                    onClick={() => {
                                                        const order = metrics.map((metric) => metric.key)
                                                        ;[order[index], order[index + direction]] = [
                                                            order[index + direction],
                                                            order[index],
                                                        ]
                                                        updateDraftGroup(group, { order })
                                                    }}
                                                />
                                            ))}
                                        </div>
                                    ))
                                )}
                            </section>
                        )
                    })}
            </div>
        </LemonModal>
    )
}
