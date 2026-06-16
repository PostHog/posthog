import { IconEye, IconNotebook, IconPulse, IconTarget } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { SCANNER_TYPE_TAG_TYPE, ScannerType, scannerTypeLabel } from '../replay_scanners/types'

function scannerTypeIcon(scannerType: ScannerType): JSX.Element {
    switch (scannerType) {
        case 'monitor':
            return <IconEye />
        case 'classifier':
            return <IconTarget />
        case 'scorer':
            return <IconPulse />
        case 'summarizer':
            return <IconNotebook />
    }
}

/**
 * Canonical badge for a scanner type — icon + per-type color + label. Use everywhere a scanner type is shown so
 * the badges stay consistent.
 * - `default` — per-type color.
 * - `muted` — greyed (e.g. a type with no scanners).
 * - `deemphasized` — greyed + struck-through, for "available but not selected" sets (e.g. the read-only config
 *   showing all types with the active one highlighted).
 * `suffix` renders extra inline content after the label (e.g. an enabled/total count).
 */
export function ScannerTypeBadge({
    scannerType,
    size = 'medium',
    variant = 'default',
    suffix,
}: {
    scannerType: ScannerType
    size?: 'small' | 'medium'
    variant?: 'default' | 'muted' | 'deemphasized'
    suffix?: React.ReactNode
}): JSX.Element {
    return (
        <LemonTag
            type={
                variant === 'default' ? SCANNER_TYPE_TAG_TYPE[scannerType] : variant === 'muted' ? 'muted' : 'default'
            }
            size={size}
            className={`w-fit${variant === 'deemphasized' ? ' opacity-50 line-through' : ''}`}
        >
            <span className="flex items-center gap-1">
                {scannerTypeIcon(scannerType)}
                {scannerTypeLabel(scannerType)}
                {suffix != null && <span>{suffix}</span>}
            </span>
        </LemonTag>
    )
}
