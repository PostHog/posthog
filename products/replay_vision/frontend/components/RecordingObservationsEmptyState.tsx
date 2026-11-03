import { useValues } from 'kea'

import * as asleepPng from '@posthog/brand/hoggies/png/asleep'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { urls } from 'scenes/urls'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { HighlightPicksStateFrame } from '../replay_scanners/components/HighlightPicksStateFrame'
import { ScanBlock } from '../utils/scanEligibility'
import { VisionDocsLink } from './DocsLink'
import { ScannerPicker } from './ScannerPicker'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)
const HedgehogAsleep = pngHoggie(asleepPng)

const SKIPPED_TITLE: Partial<Record<ScanBlock['kind'], string>> = {
    too_short: 'Too short to scan',
    too_inactive: 'Not enough activity to scan',
    too_long: 'Too long to scan',
}

const TITLE = 'No observations yet'
const BODY =
    'Summarize this recording above for chapters and a short write-up, or run a scanner to check it for something specific.'

export function RecordingObservationsEmptyState({
    sessionId,
    scanBlock,
}: {
    sessionId: string
    scanBlock: ScanBlock | null
}): JSX.Element {
    const { scanners, scannersLoading } = useValues(observationsDockLogic({ sessionId }))

    if (scanBlock) {
        return (
            <HighlightPicksStateFrame
                size="small"
                image={HedgehogAsleep}
                title={SKIPPED_TITLE[scanBlock.kind] ?? 'Replay vision skipped this recording'}
                body={scanBlock.reason}
                dataAttr="vision-observations-skipped"
                footer={
                    <VisionDocsLink
                        page="running-scanners"
                        anchor="ineligible-sessions"
                        dataAttr="vision-observations-skipped-docs"
                    >
                        Which recordings can be scanned
                    </VisionDocsLink>
                }
            />
        )
    }

    const noScanners = !scannersLoading && scanners.length === 0
    const actions = noScanners ? (
        <LemonButton
            type="primary"
            size="small"
            fullWidth
            center
            to={urls.replayVisionNewScanner()}
            data-attr="vision-observations-empty-create-scanner"
        >
            Create a scanner
        </LemonButton>
    ) : (
        <ScannerPicker sessionId={sessionId} scanBlock={scanBlock} fullWidth />
    )
    const footer = (
        <div className="mt-1 flex flex-wrap items-baseline justify-center gap-x-3 gap-y-1">
            {!noScanners && (
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    to={urls.replayVisionNewScanner()}
                    data-attr="vision-observations-empty-new-scanner"
                >
                    Create a scanner
                </LemonButton>
            )}
            <VisionDocsLink page="observations" dataAttr="vision-observations-empty-docs">
                How observations work
            </VisionDocsLink>
        </div>
    )

    return (
        <HighlightPicksStateFrame
            size="small"
            image={HedgehogMagnifyingGlass}
            title={TITLE}
            body={BODY}
            dataAttr="vision-observations-empty"
            footer={footer}
        >
            {actions}
        </HighlightPicksStateFrame>
    )
}
