import { useValues } from 'kea'

import * as asleepPng from '@posthog/brand/hoggies/png/asleep'
import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { Badge, Button } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import { ScannerType } from '../replay_scanners/types'
import { ScanBlock } from '../utils/scanEligibility'
import { VisionDocsPage, visionDocsUrl } from './DocsLink'
import { QuillScannerTypeBadge } from './QuillScannerTypeBadge'

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
        result: <Badge variant="info">Yes</Badge>,
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
        result: <Badge>Billing</Badge>,
        line: 'Help search for a payment error, then a plan change',
    },
]

function DocsLink({
    page,
    anchor,
    dataAttr,
    children,
}: {
    page: VisionDocsPage
    anchor?: string
    dataAttr: string
    children: string
}): JSX.Element {
    return (
        <Button
            variant="link"
            size="inline"
            render={
                <LinkPrimitive
                    to={`${visionDocsUrl(page)}?utm_medium=in-product&utm_campaign=empty-state-docs-link${anchor ? `#${anchor}` : ''}`}
                    target="_blank"
                />
            }
            data-attr={dataAttr}
        >
            {children}
        </Button>
    )
}

function ExampleScanRows({ className }: { className?: string }): JSX.Element {
    return (
        <div
            className={`relative flex min-w-0 flex-col ${className ?? ''}`}
            data-attr="vision-observations-empty-examples"
        >
            <span className="pb-1 text-xs text-muted-foreground">Examples, not your data</span>
            <div className="rounded border border-border opacity-60">
                {EXAMPLE_SCANS.map((scan) => (
                    <div
                        key={scan.name}
                        className="flex items-center gap-2 border-b border-border px-2 py-1.5 last:border-b-0"
                    >
                        <QuillScannerTypeBadge scannerType={scan.scannerType} iconOnly />
                        <span className="shrink-0 text-sm">{scan.name}</span>
                        <span className="shrink-0">{scan.result}</span>
                        <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{scan.line}</span>
                    </div>
                ))}
            </div>
            <div
                aria-hidden
                className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent from-45% to-background"
            />
        </div>
    )
}

export function QuillRecordingObservationsEmptyState({
    sessionId,
    scanBlock,
}: {
    sessionId: string
    scanBlock: ScanBlock | null
}): JSX.Element {
    const { scanners, scannersLoading } = useValues(observationsDockLogic({ sessionId }))

    if (scanBlock) {
        return (
            <div className="flex flex-wrap items-center gap-4 px-4 py-3" data-attr="vision-observations-skipped">
                <HedgehogAsleep className="h-14 w-14 shrink-0" />
                <div className="flex min-w-0 flex-1 basis-64 flex-col gap-0.5">
                    <span className="text-sm font-semibold">
                        {SKIPPED_TITLE[scanBlock.kind] ?? 'Replay vision skipped this recording'}
                    </span>
                    <span className="text-xs text-muted-foreground">{scanBlock.reason}</span>
                </div>
                <DocsLink
                    page="running-scanners"
                    anchor="ineligible-sessions"
                    dataAttr="vision-observations-skipped-docs"
                >
                    Which recordings can be scanned
                </DocsLink>
            </div>
        )
    }

    const noScanners = !scannersLoading && scanners.length === 0

    return (
        <div className="@container" data-attr="vision-observations-empty">
            <div className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-3 px-4 py-4 @[760px]:grid-cols-[6rem_minmax(0,1fr)_minmax(14rem,36%)] @[760px]:gap-x-5 @[760px]:px-5">
                <HedgehogMagnifyingGlass className="h-16 w-16 @[760px]:h-24 @[760px]:w-24" />
                <div className="flex min-w-0 flex-col gap-2">
                    <span className="text-sm font-semibold">No observations yet</span>
                    <p className="m-0 max-w-[52ch] text-xs text-muted-foreground">
                        Summarize this recording above for chapters and a short write-up, or run a scanner to check it
                        for something specific.
                    </p>
                    {noScanners && (
                        <div className="mt-1 flex flex-wrap gap-2">
                            <Button
                                variant="outline"
                                size="sm"
                                render={<LinkPrimitive to={urls.replayVisionNewScanner()} />}
                                data-attr="vision-observations-empty-create-scanner"
                            >
                                Create a scanner
                            </Button>
                        </div>
                    )}
                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                        {!noScanners && (
                            <Button
                                variant="link"
                                size="inline"
                                render={<LinkPrimitive to={urls.replayVisionNewScanner()} />}
                                data-attr="vision-observations-empty-new-scanner"
                            >
                                Create a scanner
                            </Button>
                        )}
                        <DocsLink page="observations" dataAttr="vision-observations-empty-docs">
                            How observations work
                        </DocsLink>
                    </div>
                </div>
                <ExampleScanRows className="col-span-2 @[760px]:col-span-1" />
            </div>
        </div>
    )
}
