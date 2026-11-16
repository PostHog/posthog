import { Badge } from '@posthog/quill'

import { ScannerType, scannerTypeLabel } from '../replay_scanners/types'
import { scannerTypeIcon } from './ScannerTypeBadge'

const SCANNER_TYPE_BADGE_VARIANT: Record<ScannerType, 'info' | 'completed' | 'warning' | 'success' | 'default'> = {
    monitor: 'info',
    classifier: 'completed',
    scorer: 'warning',
    summarizer: 'success',
    experiment: 'default',
}

export function QuillScannerTypeBadge({
    scannerType,
    iconOnly = false,
}: {
    scannerType: ScannerType
    iconOnly?: boolean
}): JSX.Element {
    return (
        <Badge variant={SCANNER_TYPE_BADGE_VARIANT[scannerType]} className="w-fit gap-1">
            {scannerTypeIcon(scannerType)}
            {!iconOnly && scannerTypeLabel(scannerType)}
        </Badge>
    )
}
