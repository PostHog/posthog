import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { HomeTabChartCard } from './HomeTabChartCard'
import { homeTabDefaultLogic, type HomeTabMetricKey, type HomeTabViewKey } from './homeTabDefaultLogic'
import { HomeTabRetentionStatTile } from './HomeTabRetentionStatTile'
import { HomeTabStatTiles } from './HomeTabStatTiles'
import type { HomeTabViewChart, HomeTabViewLayout } from './homeTabViewCharts'

interface HomeTabViewProps {
    view: Exclude<HomeTabViewKey, 'overview'>
    layout: HomeTabViewLayout
    label: string
    note?: ReactNode
}

export function HomeTabView({ view, layout, label, note }: HomeTabViewProps): JSX.Element {
    const { compare, selectedViewMetrics } = useValues(homeTabDefaultLogic)
    const { setSelectedViewMetric } = useActions(homeTabDefaultLogic)
    const { headlines, sections } = layout
    const statKeys: string[] = headlines.stats.map(({ key }) => key)
    const storedKey = selectedViewMetrics[view]
    const selectedKey = storedKey && statKeys.includes(storedKey) ? storedKey : statKeys[0]
    const primaryChart: HomeTabViewChart | undefined =
        headlines.kind === 'trend'
            ? headlines.charts[selectedKey as HomeTabMetricKey]
            : headlines.stats.find(({ key }) => key === selectedKey)?.chart

    return (
        <section className="flex flex-col gap-4" aria-label={label}>
            {headlines.kind === 'trend' ? (
                <HomeTabStatTiles
                    stats={headlines.stats}
                    compare={compare}
                    selectedKey={selectedKey}
                    onSelect={(key) => setSelectedViewMetric(view, key)}
                    label={`${label} metrics`}
                />
            ) : (
                <div className="flex snap-x snap-proximity gap-2 overflow-x-auto pb-1" aria-label={`${label} metrics`}>
                    {headlines.stats.map((stat) => (
                        <div
                            key={stat.key}
                            className="w-52 min-w-[10rem] shrink-0 snap-start @min-[60rem]/home-overview:flex-1"
                        >
                            <HomeTabRetentionStatTile
                                stat={stat}
                                selected={selectedKey === stat.key}
                                onSelect={() => setSelectedViewMetric(view, stat.key)}
                            />
                        </div>
                    ))}
                </div>
            )}

            {primaryChart && (
                <HomeTabChartCard
                    key={primaryChart.option.key}
                    option={primaryChart.option}
                    size={primaryChart.size}
                    source={primaryChart.source}
                    loadPriority={0}
                />
            )}

            {sections.map((section, sectionIndex) => (
                <section key={section.title} className="flex flex-col gap-3" aria-label={section.title}>
                    <h2 className="m-0 text-base font-semibold">{section.title}</h2>
                    {section.rows.map((row) => (
                        <div
                            key={row.map(({ option }) => option.key).join('.')}
                            className={
                                row.length > 1
                                    ? 'grid min-w-0 grid-cols-1 gap-3 @min-[44rem]/home-overview:grid-cols-2'
                                    : 'min-w-0'
                            }
                        >
                            {row.map(({ option, size, source }) => (
                                <HomeTabChartCard
                                    key={option.key}
                                    option={option}
                                    size={size}
                                    source={source}
                                    loadPriority={2 + sectionIndex}
                                />
                            ))}
                        </div>
                    ))}
                </section>
            ))}

            {note && <p className="m-0 text-xs text-secondary">{note}</p>}
        </section>
    )
}
