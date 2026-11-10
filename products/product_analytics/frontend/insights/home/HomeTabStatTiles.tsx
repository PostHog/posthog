import type { DateRange } from '~/queries/schema/schema-general'

import { getHomeTabStatQueries } from './homeTabDefaultTiles'
import { HomeTabStatTile } from './HomeTabStatTile'

interface HomeTabStatTilesProps {
    dateRange: DateRange
    compare: boolean
}

export function HomeTabStatTiles({ dateRange, compare }: HomeTabStatTilesProps): JSX.Element {
    const stats = getHomeTabStatQueries(dateRange, compare)

    return (
        <div className="flex snap-x snap-proximity gap-2 overflow-x-auto pb-1" aria-label="Overview metrics">
            {stats.map((stat) => (
                <div
                    key={stat.key}
                    className="w-52 min-w-[10rem] shrink-0 snap-start @min-[60rem]/home-overview:flex-1"
                >
                    <HomeTabStatTile key={stat.trendKey ?? stat.key} stat={stat} compare={compare} />
                </div>
            ))}
        </div>
    )
}
