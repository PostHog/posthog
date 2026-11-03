import { LemonTag } from '@posthog/lemon-ui'

import { scannerTypeIcon } from '../../components/ScannerTypeBadge'
import { SCANNER_TYPE_TAG_TYPE, ScannerType } from '../types'

export function HighlightFeedScannerChip({
    scannerName,
    scannerType,
}: {
    scannerName: string
    scannerType: ScannerType | undefined
}): JSX.Element {
    return (
        <>
            {scannerType && (
                <LemonTag
                    type={SCANNER_TYPE_TAG_TYPE[scannerType]}
                    className="size-6 shrink-0 justify-center !rounded-full !p-0"
                >
                    {scannerTypeIcon(scannerType)}
                </LemonTag>
            )}
            <span className="truncate font-medium">{scannerName}</span>
        </>
    )
}
