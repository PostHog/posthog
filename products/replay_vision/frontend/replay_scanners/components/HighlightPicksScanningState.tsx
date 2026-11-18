import { useMountedLogic, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'

import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { HighlightPicksStateFrame } from './HighlightPicksStateFrame'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)
const PLACEHOLDER_ROWS = 3

export function HighlightPicksScanningState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { burstSessionIds, burstCounts } = useValues(highlightPicksStarterLogic(picksLogic.props))
    const total = burstSessionIds.length
    const finished = burstCounts.succeeded + burstCounts.failed

    return (
        <>
            <HighlightPicksStateFrame
                size={size}
                image={HedgehogMagnifyingGlass}
                title="Scanning your sessions"
                body="Highlights show up here a few minutes after scans finish."
                dataAttr="vision-highlight-picks-scanning"
            >
                <LemonProgress percent={total === 0 ? 100 : (finished / total) * 100} />
                <span className="text-xs text-secondary" translate="no">
                    {finished} of {total} scanned
                </span>
            </HighlightPicksStateFrame>
            <div className="flex flex-col gap-2 p-2" aria-busy>
                {Array.from({ length: Math.min(PLACEHOLDER_ROWS, Math.max(1, total - finished)) }, (_, i) => (
                    <LemonSkeleton key={i} className="h-16 rounded" />
                ))}
            </div>
        </>
    )
}
