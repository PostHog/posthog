import { useValues } from 'kea'

import * as asleepPng from '@posthog/brand/hoggies/png/asleep'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { SCANNER_TYPE_TAG_TYPE, ScannerType } from '../replay_scanners/types'
import { ScanBlock } from '../utils/scanEligibility'
import { VisionDocsLink } from './DocsLink'
import { ScannerPicker } from './ScannerPicker'
import { scannerTypeIcon } from './ScannerTypeBadge'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)
const HedgehogAsleep = pngHoggie(asleepPng)

const SKIPPED_TITLE: Partial<Record<ScanBlock['kind'], string>> = {
    too_short: 'Too short to scan',
    too_inactive: 'Not enough activity to scan',
    too_long: 'Too long to scan',
}

interface ExampleScan {
    scannerType: ScannerType
    name: string
    result: JSX.Element
    line: string
}

// Invented, not sampled.
const EXAMPLE_SCANS: ExampleScan[] = [
    {
        scannerType: 'monitor',
        name: 'Checkout friction',
        result: (
            <LemonTag size="medium" type="highlight">
                Yes
            </LemonTag>
        ),
        line: 'Nine clicks on a disabled payment button, no request sent',
    },
    {
        scannerType: 'scorer',
        name: 'Frustration',
        result: <span className="font-semibold">8</span>,
        line: 'A rejected card and a retry, then an abandoned purchase',
    },
    {
        scannerType: 'classifier',
        name: 'Support intent',
        result: (
            <LemonTag size="medium" type="option">
                Billing
            </LemonTag>
        ),
        line: 'Help search for a payment error, then a plan change',
    },
]

function ExampleScanRows({ className }: { className?: string }): JSX.Element {
    return (
        <div className={cn('relative flex min-w-0 flex-col', className)} data-attr="vision-observations-empty-examples">
            <span className="pb-1 text-xs text-secondary">Examples, not your data</span>
            <div className="rounded border border-primary opacity-60">
                {EXAMPLE_SCANS.map((scan) => (
                    <div
                        key={scan.name}
                        className="flex items-center gap-2 border-b border-primary px-2 py-1.5 last:border-b-0"
                    >
                        <LemonTag type={SCANNER_TYPE_TAG_TYPE[scan.scannerType]} size="small">
                            {scannerTypeIcon(scan.scannerType)}
                        </LemonTag>
                        <span className="shrink-0 text-sm">{scan.name}</span>
                        <span className="shrink-0">{scan.result}</span>
                        <span className="min-w-0 flex-1 truncate text-xs text-secondary">{scan.line}</span>
                    </div>
                ))}
            </div>
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent from-45% to-surface-primary"
            />
        </div>
    )
}

export type ObservationsSurface = 'watch' | 'tab'

const SKIPPED_ATTR: Record<ObservationsSurface, string> = {
    watch: 'vision-observations-skipped',
    tab: 'vision-observations-tab-skipped',
}
const EMPTY_ATTR: Record<ObservationsSurface, string> = {
    watch: 'vision-observations-empty',
    tab: 'vision-observations-tab-empty',
}

export function RecordingObservationsEmptyState({
    sessionId,
    scanBlock,
    surface,
}: {
    sessionId: string
    scanBlock: ScanBlock | null
    surface: ObservationsSurface
}): JSX.Element {
    const { scanners, scannersLoading } = useValues(observationsDockLogic({ sessionId }))

    if (scanBlock) {
        return (
            <div className="flex flex-wrap items-center gap-4 px-4 py-3" data-attr={SKIPPED_ATTR[surface]}>
                <HedgehogAsleep className="h-14 w-14 shrink-0" />
                <div className="flex min-w-0 flex-1 basis-64 flex-col gap-0.5">
                    <span className="text-sm font-semibold">
                        {SKIPPED_TITLE[scanBlock.kind] ?? 'Replay vision skipped this recording'}
                    </span>
                    <span className="text-xs text-secondary">{scanBlock.reason}</span>
                </div>
                <VisionDocsLink
                    page="running-scanners"
                    anchor="ineligible-sessions"
                    dataAttr="vision-observations-skipped-docs"
                >
                    Which recordings can be scanned
                </VisionDocsLink>
            </div>
        )
    }

    const noScanners = !scannersLoading && scanners.length === 0

    return (
        <div className="@container" data-attr={EMPTY_ATTR[surface]}>
            <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-3 px-4 py-4 @[760px]:grid-cols-[6rem_minmax(0,1fr)_minmax(14rem,36%)] @[760px]:gap-x-5 @[760px]:px-5">
                <HedgehogMagnifyingGlass className="h-16 w-16 @[760px]:h-24 @[760px]:w-24" />
                <div className="flex min-w-0 flex-col gap-2">
                    <span className="text-sm font-semibold">No observations yet</span>
                    <p className="m-0 max-w-[52ch] text-xs text-secondary">
                        Summarize this recording above for chapters and a short write-up, or run a scanner to check it
                        for something specific.
                    </p>
                    <div className="mt-1 flex flex-wrap gap-2">
                        {noScanners ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                to={urls.replayVisionNewScanner()}
                                data-attr="vision-observations-empty-create-scanner"
                            >
                                Create a scanner
                            </LemonButton>
                        ) : (
                            <ScannerPicker sessionId={sessionId} scanBlock={null} type="secondary" />
                        )}
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                        {!noScanners && (
                            <Link to={urls.replayVisionNewScanner()} data-attr="vision-observations-empty-new-scanner">
                                Create a scanner
                            </Link>
                        )}
                        <VisionDocsLink page="observations" dataAttr="vision-observations-empty-docs">
                            How observations work
                        </VisionDocsLink>
                    </div>
                </div>
                <ExampleScanRows className="col-span-2 @[760px]:col-span-1" />
            </div>
        </div>
    )
}
