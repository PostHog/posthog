import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import posthog from 'lib/posthog-typed'
import { urls } from 'scenes/urls'

import { VisionDocsLink } from '../../components/DocsLink'
import { ObservationPreviewCard } from '../../components/ObservationPreviewCard'
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { replayScannersLogic } from '../replayScannersLogic'
import { LIMIT_REACHED_TOOLTIP } from '../scannerCopy'
import { scannerHighlightsLogic } from '../scannerHighlightsLogic'
import { ReplayScanner } from '../types'
import { CreateScannerButton } from './CreateScannerButton'

function HighlightRail({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    const { recentObservations, recentObservationsLoading, recentObservationsFailed } =
        useValues(scannerHighlightsLogic)
    const { loadRecentObservations } = useActions(scannerHighlightsLogic)

    const observations = recentObservations?.[scanner.id]
    if (recentObservationsLoading && observations === undefined) {
        return (
            <div className="flex gap-3 overflow-hidden">
                {[0, 1, 2].map((i) => (
                    <LemonSkeleton key={i} className="w-72 h-24 shrink-0 rounded" />
                ))}
            </div>
        )
    }
    if (recentObservationsFailed && observations === undefined) {
        return (
            <div className="flex items-center gap-2 text-sm text-secondary border rounded p-3">
                <span>Couldn't load recent observations.</span>
                <LemonButton size="xsmall" type="secondary" onClick={() => loadRecentObservations()}>
                    Try again
                </LemonButton>
            </div>
        )
    }
    if (!observations || observations.length === 0) {
        return (
            <div className="text-sm text-secondary border border-dashed rounded p-3">
                No observations yet. <Link to={urls.replayVision(scanner.id)}>Open the scanner</Link> to run it on a
                session.
            </div>
        )
    }
    return (
        <div className="flex gap-3 overflow-x-auto pb-1">
            {observations.map((observation, index) => (
                <ObservationPreviewCard key={observation.id} observation={observation} position={index} />
            ))}
        </div>
    )
}

export function ScannerHighlightsView(): JSX.Element {
    const { scanners, scannersLoading, scannersPage, scannersPageSize, scannersTotal, hasActiveFilters } =
        useValues(replayScannersLogic)
    const { setScannersFilters } = useActions(replayScannersLogic)

    const pagination = usePagination(scanners, {
        controlled: true,
        pageSize: scannersPageSize,
        currentPage: scannersPage,
        entryCount: scannersTotal,
        onForward: () => setScannersFilters({ page: scannersPage + 1 }),
        onBackward: () => setScannersFilters({ page: scannersPage - 1 }),
    })

    if (scannersLoading && scanners.length === 0) {
        return (
            <div className="flex flex-col gap-6">
                {[0, 1, 2].map((i) => (
                    <div key={i} className="flex flex-col gap-3">
                        <LemonSkeleton className="w-64 h-6" />
                        <div className="flex gap-3 overflow-hidden">
                            {[0, 1, 2].map((j) => (
                                <LemonSkeleton key={j} className="w-72 h-24 shrink-0 rounded" />
                            ))}
                        </div>
                    </div>
                ))}
            </div>
        )
    }

    if (scanners.length === 0) {
        return hasActiveFilters ? (
            <span className="text-muted">No scanners match your filters.</span>
        ) : (
            <div className="flex flex-col items-center gap-3 p-8 text-center">
                <div className="text-muted">No scanners yet.</div>
                <CreateScannerButton
                    acceptedLabel="Create your first scanner"
                    dataAttr="vision-scanner-create-empty"
                    size="medium"
                />
                <VisionDocsLink page="creating-scanners" dataAttr="vision-empty-docs-link-scanners">
                    Learn how scanners work
                </VisionDocsLink>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-6">
            {scanners.map((scanner) => (
                <section key={scanner.id} className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <Link
                            to={urls.replayVision(scanner.id)}
                            className="font-semibold text-base text-primary"
                            data-attr="vision-highlight-scanner-open"
                            onClick={() => {
                                posthog.capture('replay_vision_highlight_scanner_opened', {
                                    scanner_id: scanner.id,
                                    scanner_type: scanner.scanner_type,
                                })
                            }}
                        >
                            {scanner.name || '(untitled)'}
                        </Link>
                        <ScannerTypeBadge scannerType={scanner.scanner_type} />
                        {!scanner.enabled && <LemonTag>Disabled</LemonTag>}
                        {scanner.limit_reached && (
                            <Tooltip title={LIMIT_REACHED_TOOLTIP}>
                                <LemonTag type="danger">Limit reached</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    {scanner.description && <div className="text-muted text-sm">{scanner.description}</div>}
                    <HighlightRail scanner={scanner} />
                </section>
            ))}
            <PaginationControl {...pagination} nouns={['scanner', 'scanners']} />
        </div>
    )
}
