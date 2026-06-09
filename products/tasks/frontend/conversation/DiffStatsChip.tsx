import { JSX } from 'react'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { IconList } from './primitives/icons'

interface DiffStatsChipProps {
    additions: number
    deletions: number
}

/**
 * Read-only +N/-M added/removed lines chip.
 *
 * Ported from PostHog Code's `DiffStatsChip`. The Electron version derived
 * counts from a live `Task` and toggled a review panel on click; here the
 * counts are passed in directly and the chip is non-interactive (the transcript
 * is read-only, so there is no review panel to open).
 */
export function DiffStatsChip({ additions, deletions }: DiffStatsChipProps): JSX.Element | null {
    if (additions === 0 && deletions === 0) {
        return null
    }

    return (
        <Tooltip title="Lines changed">
            <LemonTag type="muted" className="select-none tabular-nums">
                <IconList className="shrink-0 text-muted" style={{ fontSize: 12 }} />
                {additions > 0 && <span className="text-success">+{additions}</span>}
                {deletions > 0 && <span className="text-danger">-{deletions}</span>}
            </LemonTag>
        </Tooltip>
    )
}
