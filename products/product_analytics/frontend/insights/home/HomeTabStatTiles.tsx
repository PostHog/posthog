import type { DateRange } from '~/queries/schema/schema-general'

import type { HomeTabMetricKey } from './homeTabDefaultLogic'
import { getHomeTabStatQueries } from './homeTabDefaultTiles'
import { HomeTabStatTile } from './HomeTabStatTile'

interface HomeTabStatTilesProps {
    dateRange: DateRange
    compare: boolean
    selectedKey: HomeTabMetricKey
    onSelect: (key: HomeTabMetricKey) => void
}

export function HomeTabStatTiles({ dateRange, compare, selectedKey, onSelect }: HomeTabStatTilesProps): JSX.Element {
    const stats = getHomeTabStatQueries(dateRange, compare)

    return (
        <div className="flex snap-x snap-proximity gap-2 overflow-x-auto pb-1" aria-label="Overview metrics">
            {stats.map((stat) => (
                <div
                    key={stat.key}
                    className="w-52 min-w-[10rem] shrink-0 snap-start @min-[60rem]/home-overview:flex-1"
                >
                    <HomeTabStatTile
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
