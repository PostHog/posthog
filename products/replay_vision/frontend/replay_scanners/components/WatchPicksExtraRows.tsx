import { useMountedLogic, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import type { WatchFeedItemApi } from '../../generated/api.schemas'
import { watchPicksLogic } from '../watchPicksLogic'
import { watchPicksStaleLogic } from '../watchPicksStaleLogic'
import { watchPicksStarterLogic } from '../watchPicksStarterLogic'
import { WatchPickRow } from './WatchPickRow'

export function WatchPicksExtraRows(): JSX.Element | null {
    const picksLogic = useMountedLogic(watchPicksLogic)
    const { nextBest } = useValues(watchPicksStaleLogic(picksLogic.props))
    const { scannedAnyway } = useValues(watchPicksStarterLogic(picksLogic.props))
    const ref = useRef<HTMLDivElement>(null)
    const rows = scannedAnyway ?? nextBest

    useEffect(() => {
        if (rows) {
            ref.current?.scrollIntoView({ block: 'nearest' })
        }
    }, [rows])

    if (!rows) {
        return null
    }
    return (
        <div ref={ref} className="flex flex-col gap-0.5 border-t p-1" data-attr="vision-watch-picks-extra-rows">
            <span className="px-2 pt-1 text-xs font-semibold text-secondary">
                {scannedAnyway ? 'Scanned, nothing notable' : 'Newest results, not ranked'}
            </span>
            {rows.length === 0 ? (
                <span className="px-2 pb-1 text-xs text-secondary">No finished scans this week.</span>
            ) : (
                rows.map((observation, index) => (
                    <WatchPickRow
                        key={observation.id}
                        item={{ observation, reason: { kind: 'recent' } } as WatchFeedItemApi}
                        position={index}
                        isActive={false}
                    />
                ))
            )}
        </div>
    )
}
