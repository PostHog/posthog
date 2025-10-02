import clsx from 'clsx'
import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { UsageFilters } from './UsageFilters'
import { UsageQueryTile } from './common'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'

export function Usage({ tabId }: { tabId: string }): JSX.Element {
    const { tiles } = useValues(embeddedAnalyticsLogic({ tabId }))

    return (
        <>
            <UsageFilters tabId={tabId} />
            <UsageTiles tiles={tiles} />
        </>
    )
}

const UsageTiles = (props: { tiles: UsageQueryTile[] }): JSX.Element => {
    const { tiles } = props
    return (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-x-4 gap-y-8">
            {tiles.map((tile, i) => {
                if (tile.kind === 'query') {
                    return <UsageQueryTileItem key={i} tile={tile} />
                }
                return null
            })}
        </div>
    )
}

const UsageQueryTileItem = ({ tile }: { tile: UsageQueryTile }): JSX.Element => {
    const { query, title, layout } = tile

    return (
        <div
            className={clsx(
                'col-span-1 row-span-1 flex flex-col',
                layout.colSpanClassName ?? 'md:col-span-6',
                layout.rowSpanClassName ?? 'md:row-span-1',
                layout.orderWhenLargeClassName ?? 'xxl:order-12',
                layout.className
            )}
        >
            {title && (
                <div className="flex flex-row items-center mb-3">
                    <h2>{title}</h2>
                </div>
            )}

            <Query
                key={`${tile.tileId}-${query.kind === 'DataVisualizationNode' ? JSON.stringify(query.chartSettings?.seriesBreakdownColumn) : 'no-breakdown'}`}
                query={query}
                readOnly={true}
            />
        </div>
    )
}
