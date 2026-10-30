import { useActions, useValues } from 'kea'

import { IconChevronDown, IconEye } from '@posthog/icons'
import { LemonButton, LemonInput, Link, Spinner } from '@posthog/lemon-ui'

import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown/LemonDropdown'
import { urls } from 'scenes/urls'

import type { ReplayScannerApi } from '../generated/api.schemas'
import { observationsDockLogic } from '../logics/observationsDockLogic'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { quotaUx } from '../utils/quotaProjection'
import { ScanBlock } from '../utils/scanEligibility'
import { ScannerTypeBadge } from './ScannerTypeBadge'

export function ScannerPicker({
    sessionId,
    scanBlock,
    type = 'primary',
    placement = 'bottom-start',
    fullWidth = false,
}: {
    sessionId: string
    scanBlock: ScanBlock | null
    type?: 'primary' | 'secondary'
    placement?: 'bottom-start' | 'top-start'
    fullWidth?: boolean
}): JSX.Element {
    const logic = observationsDockLogic({ sessionId })
    const { scanners, scannersLoading, filteredScanners, scannerSearch, scannerPickerOpen, observing } =
        useValues(logic)
    const { observe, setScannerSearch, setScannerPickerOpen } = useActions(logic)
    const { quota } = useValues(visionQuotaLogic)
    const { disabledReason: quotaDisabledReason, tooltip: quotaTooltip } = quotaUx(quota)

    return (
        <LemonDropdown
            visible={scannerPickerOpen}
            onVisibilityChange={setScannerPickerOpen}
            closeOnClickInside={false}
            placement={placement}
            overlay={
                <div className="w-80">
                    <div className="p-1 border-b">
                        <LemonInput
                            data-attr="vision-observations-tab-search"
                            type="search"
                            size="small"
                            placeholder="Search scanners…"
                            value={scannerSearch}
                            onChange={setScannerSearch}
                            autoFocus
                        />
                    </div>
                    <div className="max-h-80 overflow-y-auto p-1">
                        {scanners.length === 0 && scannersLoading ? (
                            <div className="flex items-center gap-2 px-2 py-3 text-sm text-muted">
                                <Spinner /> Loading scanners…
                            </div>
                        ) : scanners.length === 0 ? (
                            <Link
                                data-attr="vision-observations-open-scanners"
                                to={urls.replayVision()}
                                target="_blank"
                                className="block px-2 py-3 text-sm"
                            >
                                No scanners yet. Create one
                            </Link>
                        ) : filteredScanners.length === 0 ? (
                            <div className="px-2 py-3 text-sm text-muted">No scanners match your search.</div>
                        ) : (
                            filteredScanners.map((scanner: ReplayScannerApi) => (
                                <LemonButton
                                    key={scanner.id}
                                    fullWidth
                                    size="small"
                                    onClick={() => observe(scanner.id)}
                                    disabledReason={observing ? 'Starting an observation…' : undefined}
                                    data-attr="vision-scan-pick-scanner"
                                    data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                                >
                                    <span className="flex items-center justify-between gap-2 w-full">
                                        <span className="truncate">{scanner.name}</span>
                                        <span className="shrink-0">
                                            <ScannerTypeBadge scannerType={scanner.scanner_type} size="small" />
                                        </span>
                                    </span>
                                </LemonButton>
                            ))
                        )}
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type={type}
                fullWidth={fullWidth}
                center={fullWidth}
                icon={<IconEye />}
                sideIcon={<IconChevronDown />}
                loading={observing}
                disabledReason={scanBlock?.reason ?? quotaDisabledReason}
                tooltip={quotaTooltip}
                data-attr="vision-scan-recording"
            >
                Scan this recording
            </LemonButton>
        </LemonDropdown>
    )
}
