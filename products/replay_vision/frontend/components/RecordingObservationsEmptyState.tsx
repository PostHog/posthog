import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'

import { pngHoggie } from 'lib/brand/hoggies'

import { HighlightPicksStateFrame } from '../replay_scanners/components/HighlightPicksStateFrame'
import { ScanBlock } from '../utils/scanEligibility'
import { ScannerPicker } from './ScannerPicker'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function RecordingObservationsEmptyState({
    sessionId,
    scanBlock,
}: {
    sessionId: string
    scanBlock: ScanBlock | null
}): JSX.Element {
    if (scanBlock) {
        return (
            <HighlightPicksStateFrame
                size="small"
                image={HedgehogMagnifyingGlass}
                title="Replay vision skipped this recording"
                body={scanBlock.reason}
                dataAttr="vision-observations-skipped"
            />
        )
    }
    return (
        <HighlightPicksStateFrame
            size="small"
            image={HedgehogMagnifyingGlass}
            title="No observations yet"
            body="Summarize this recording or run a scanner to see what it finds here."
            dataAttr="vision-observations-empty"
        >
            <ScannerPicker sessionId={sessionId} scanBlock={scanBlock} />
        </HighlightPicksStateFrame>
    )
}
