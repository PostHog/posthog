import { useActions, useValues } from 'kea'

import { IconChevronDown, IconChevronRight, IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import type { ChartTheme } from '@posthog/quill-charts'

import { SamplingNotice, SamplingRate } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { OverviewMetricCardGrid, OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { OverviewMetricConfigModal } from './OverviewMetricConfigModal'
import { OVERVIEW_METRIC_GROUPS, overviewMetricsForGroup } from './overviewMetricConfiguration'
import { overviewMetricsLogic } from './overviewMetricsLogic'

export interface AdPerformanceOverviewMetricsProps {
    items: OverviewMetricCardItem[]
    loading: boolean
    numSkeletons: number
    samplingRate?: SamplingRate
    sparklineTheme?: ChartTheme
    labelFromKey: (key: string) => React.ReactNode
    viewKey: string
}

export function AdPerformanceOverviewMetrics({
    items,
    loading,
    numSkeletons,
    samplingRate,
    sparklineTheme,
    labelFromKey,
    viewKey,
}: AdPerformanceOverviewMetricsProps): JSX.Element {
    const logic = overviewMetricsLogic({ viewKey })
    const { configuration } = useValues(logic)
    const { configureMetrics, setGroupCollapsed } = useActions(logic)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconGear />}
                    onClick={() => configureMetrics(configuration)}
                    disabledReason={loading ? 'Wait for metrics to load' : undefined}
                    data-attr="marketing-configure-metrics"
                >
                    Configure metrics
                </LemonButton>
            </div>
            {OVERVIEW_METRIC_GROUPS.map(({ key: group, label, description }) => {
                const metrics = overviewMetricsForGroup(items, group, configuration)
                const visibleMetrics = metrics.filter((item) => !configuration[group].hidden.includes(item.key))
                const collapsed = configuration[group].collapsed
                return (
                    <section key={group} aria-label={label}>
                        <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                            <LemonButton
                                size="small"
                                icon={collapsed ? <IconChevronRight /> : <IconChevronDown />}
                                onClick={() => setGroupCollapsed(group, !collapsed)}
                                aria-expanded={!collapsed}
                                aria-controls={`${viewKey}-${group}-metrics`}
                                data-attr={`marketing-metrics-toggle-${group}`}
                            >
                                {label}
                            </LemonButton>
                            <span className="text-xs text-secondary">{description}</span>
                            {!loading && (
                                <span className="text-xs text-secondary">
                                    {visibleMetrics.length} / {metrics.length}
                                </span>
                            )}
                        </div>
                        <div id={`${viewKey}-${group}-metrics`} hidden={collapsed}>
                            {loading || visibleMetrics.length > 0 ? (
                                <OverviewMetricCardGrid
                                    sparklineTheme={sparklineTheme}
                                    className="grid-cols-[repeat(auto-fit,minmax(12rem,1fr))]"
                                    items={visibleMetrics}
                                    loading={loading}
                                    numSkeletons={
                                        group === 'platforms'
                                            ? Math.min(numSkeletons, 9)
                                            : Math.max(numSkeletons - 9, 2)
                                    }
                                    emptyMessage="-"
                                    labelFromKey={labelFromKey}
                                />
                            ) : (
                                <div className="flex flex-wrap items-center gap-2 py-2 text-sm text-secondary">
                                    <span>
                                        {metrics.length
                                            ? 'All metrics in this group are hidden.'
                                            : 'No metrics available for this group.'}
                                    </span>
                                    {metrics.length > 0 && (
                                        <LemonButton size="small" onClick={() => configureMetrics(configuration)}>
                                            Choose metrics
                                        </LemonButton>
                                    )}
                                </div>
                            )}
                        </div>
                    </section>
                )
            })}
            <SamplingNotice samplingRate={samplingRate} />
            <OverviewMetricConfigModal items={items} viewKey={viewKey} />
        </div>
    )
}
