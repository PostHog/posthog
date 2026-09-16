import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { ScoutGroupKey } from '../../../utils/scoutGroups'

const DOT_CLASS: Record<ScoutGroupKey, string> = {
    needs_you: 'bg-danger',
    working: 'bg-success',
    watching: 'bg-secondary',
    // Outlined rather than filled: a dry-run scout is running, but nothing reaches the inbox.
    dry_run: 'border border-dashed border-brand-blue',
    settling_in: 'bg-brand-blue',
    off: 'border border-secondary',
}

const DOT_TOOLTIP: Record<ScoutGroupKey, string> = {
    needs_you: 'This scout needs a decision from you',
    working: 'Filed something recently',
    watching: 'Running — nothing worth filing',
    dry_run: 'Running, but filing nothing',
    settling_in: 'Too new to judge',
    off: 'Turned off',
}

/** The state glyph at the head of a roster row, matching its group. */
export function ScoutStatusDot({ group }: { group: ScoutGroupKey }): JSX.Element {
    return (
        <Tooltip title={DOT_TOOLTIP[group]}>
            <span className={cn('size-2 shrink-0 rounded-full', DOT_CLASS[group])} />
        </Tooltip>
    )
}
