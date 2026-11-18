import { useMountedLogic, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import type { HighlightFeedItemApi } from '../../generated/api.schemas'
import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStaleLogic } from '../highlightPicksStaleLogic'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { HighlightPickRow } from './HighlightPickRow'

export function HighlightPicksExtraRows(): JSX.Element | null {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { nextBest } = useValues(highlightPicksStaleLogic(picksLogic.props))
    const { scannedAnyway } = useValues(highlightPicksStarterLogic(picksLogic.props))
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
        <div ref={ref} className="flex flex-col gap-0.5 border-t p-1" data-attr="vision-highlight-picks-extra-rows">
            <span className="px-2 pt-1 text-xs font-semibold text-secondary">
                {scannedAnyway ? 'Scanned, nothing notable' : 'Newest results, not ranked'}
            </span>
            {rows.length === 0 ? (
                <span className="px-2 pb-1 text-xs text-secondary">No finished scans this week.</span>
            ) : (
                rows.map((observation, index) => (
                    <HighlightPickRow
                        key={observation.id}
                        item={{ observation, reason: { kind: 'recent' } } as HighlightFeedItemApi}
                        position={index}
                        isActive={false}
                    />
                ))
            )}
        </div>
    )
}
