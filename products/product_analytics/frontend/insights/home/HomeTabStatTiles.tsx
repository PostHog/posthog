import type { HomeTabMetricKey } from './homeTabDefaultLogic'
import type { HomeTabStatQuery } from './homeTabDefaultTiles'
import { HomeTabStatTile } from './HomeTabStatTile'

interface HomeTabStatTilesProps {
    stats: HomeTabStatQuery[]
    compare: boolean
    selectedKey: string
    onSelect: (key: HomeTabMetricKey) => void
    label: string
}

export function HomeTabStatTiles({ stats, compare, selectedKey, onSelect, label }: HomeTabStatTilesProps): JSX.Element {
    return (
        <div className="flex snap-x snap-proximity gap-2 overflow-x-auto pb-1" aria-label={label}>
            {stats.map((stat) => (
                <div
                    key={stat.key}
                    className="w-52 min-w-[10rem] shrink-0 snap-start @min-[60rem]/home-overview:flex-1"
                >
                    <HomeTabStatTile
                        key={stat.trendKey ?? stat.key}
                        stat={stat}
                        compare={compare}
                        selected={selectedKey === stat.key}
                        onSelect={() => onSelect(stat.key)}
                    />
                </div>
            ))}
        </div>
    )
}
