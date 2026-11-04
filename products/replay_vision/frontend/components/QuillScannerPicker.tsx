import { useActions, useValues } from 'kea'

import { IconChevronDown, IconEye } from '@posthog/icons'
import { Button, Input, Popover, PopoverContent, PopoverTrigger, Spinner } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock } from '../utils/scanEligibility'
import { QuillScannerTypeBadge } from './QuillScannerTypeBadge'

export function QuillScannerPicker({
    sessionId,
    scanBlock,
    variant = 'primary',
}: {
    sessionId: string
    scanBlock: ScanBlock | null
    variant?: 'primary' | 'outline'
}): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { scanners, scannersLoading, filteredScanners, scannerSearch, scannerPickerOpen, observing } =
        useValues(logic)
    const { observe, setScannerSearch, setScannerPickerOpen } = useActions(logic)
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)

    return (
        <Popover open={scannerPickerOpen} onOpenChange={setScannerPickerOpen}>
            <PopoverTrigger
                render={
                    <Button
                        size="sm"
                        variant={variant}
                        loading={observing}
                        disabledReason={scanBlock?.reason ?? quotaDisabledReason}
                        tooltip={quotaTooltip}
                        data-attr="vision-scan-recording"
                    />
                }
            >
                <IconEye />
                Scan this recording
                <IconChevronDown />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-80 p-0">
                <div className="p-1 border-b border-border">
                    <Input
                        type="search"
                        size="sm"
                        placeholder="Search scanners…"
                        value={scannerSearch}
                        onChange={(event) => setScannerSearch(event.target.value)}
                        autoFocus
                        data-attr="vision-observations-tab-search"
                    />
                </div>
                <div className="max-h-80 overflow-y-auto p-1">
                    {scanners.length === 0 && scannersLoading ? (
                        <div className="flex items-center gap-2 px-2 py-3 text-sm text-muted-foreground">
                            <Spinner /> Loading scanners…
                        </div>
                    ) : scanners.length === 0 ? (
                        <Button
                            variant="link"
                            size="inline"
                            className="px-2 py-3 text-sm"
                            render={<LinkPrimitive to={urls.replayVision()} target="_blank" />}
                            data-attr="vision-observations-open-scanners"
                        >
                            No scanners yet. Create one
                        </Button>
                    ) : filteredScanners.length === 0 ? (
                        <div className="px-2 py-3 text-sm text-muted-foreground">No scanners match your search.</div>
                    ) : (
                        filteredScanners.map((scanner: ReplayScannerApi) => (
                            <Button
                                key={scanner.id}
                                size="row"
                                left
                                className="w-full"
                                onClick={() => observe(scanner.id)}
                                disabledReason={observing ? 'Starting an observation…' : undefined}
                                data-attr="vision-scan-pick-scanner"
                                data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                            >
                                <span className="truncate">{scanner.name}</span>
                                <span className="ml-auto shrink-0">
                                    <QuillScannerTypeBadge scannerType={scanner.scanner_type} />
                                </span>
                            </Button>
                        ))
                    )}
                </div>
            </PopoverContent>
        </Popover>
    )
}
