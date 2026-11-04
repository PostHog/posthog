import { useMountedLogic, useValues } from 'kea'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { Progress, Skeleton } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'

import { highlightPicksLogic } from '../highlightPicksLogic'
import { highlightPicksStarterLogic } from '../highlightPicksStarterLogic'
import { QuillHighlightPicksStateFrame } from './QuillHighlightPicksStateFrame'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)
const PLACEHOLDER_ROWS = 3

export function QuillHighlightPicksScanningState({ size }: { size: 'small' | 'large' }): JSX.Element {
    const picksLogic = useMountedLogic(highlightPicksLogic)
    const { burstSessionIds, burstCounts } = useValues(highlightPicksStarterLogic(picksLogic.props))
    const total = burstSessionIds.length
    const finished = burstCounts.succeeded + burstCounts.failed

    return (
        <>
            <QuillHighlightPicksStateFrame
                size={size}
                image={HedgehogMagnifyingGlass}
                title="Scanning your sessions"
                body="Highlights show up here a few minutes after scans finish."
                dataAttr="vision-highlight-picks-scanning"
            >
                <Progress value={total === 0 ? 100 : (finished / total) * 100} />
                <span className="text-xs text-muted-foreground" translate="no">
                    {finished} of {total} scanned
                </span>
            </QuillHighlightPicksStateFrame>
            <div data-quill className="flex flex-col gap-2 p-2" aria-busy>
                {Array.from({ length: Math.min(PLACEHOLDER_ROWS, Math.max(1, total - finished)) }, (_, i) => (
                    <Skeleton key={i} className="h-16 rounded" />
                ))}
            </div>
        </>
    )
}
