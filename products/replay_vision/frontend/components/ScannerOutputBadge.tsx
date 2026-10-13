import { LemonTag } from '@posthog/lemon-ui'

import { SCANNER_TYPE_TAG_TYPE, SUCCEEDED_OUTPUT_LABEL, ScannerType } from '../replay_scanners/types'
import { scannerTypeIcon } from './ScannerTypeBadge'

/**
 * Badge for what a scanner produced (Verdict, Categories, Score, Summary), named the way the observation
 * detail page names it. Carries the scanner type's icon and color, so a type stays recognizable at a glance.
 * Use ScannerTypeBadge instead wherever the scanner type itself is what's being shown.
 */
export function ScannerOutputBadge({
    scannerType,
    size = 'medium',
}: {
    scannerType: ScannerType
    size?: 'small' | 'medium'
}): JSX.Element {
    return (
        <LemonTag type={SCANNER_TYPE_TAG_TYPE[scannerType]} size={size} className="w-fit">
            <span className="flex items-center gap-1">
                {scannerTypeIcon(scannerType)}
                {SUCCEEDED_OUTPUT_LABEL[scannerType]}
            </span>
        </LemonTag>
    )
}
