import { useMemo } from 'react'

import { Text } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { OneAccountIssue } from '../../recommendations/types'
import { share } from '../impactFormat'
import { type Part, PartsBar } from './PartsBar'
import { fade, useImpactPalette } from './useImpactPalette'

// The issue's sessions split into the largest account and every other account, so one customer's problem reads
// differently from a general one.
export function OneAccountSignal({ issue }: { issue: OneAccountIssue }): JSX.Element {
    const palette = useImpactPalette()
    const top = issue.top_account
    const name = top.name ?? top.key
    const others = Math.max(issue.accounts - 1, 0)
    const parts = useMemo<Part[]>(
        () => [
            { key: 'top', label: name, value: top.session_share * issue.sessions, color: palette.audience },
            {
                key: 'others',
                label: 'Other accounts',
                value: (1 - top.session_share) * issue.sessions,
                color: fade(palette.audience, 0.3),
            },
        ],
        [name, top.session_share, issue.sessions, palette]
    )
    return (
        <div className="flex w-full max-w-64 flex-col gap-1.5">
            <div className="flex min-w-0 items-baseline justify-between gap-2">
                <Text render={<span />} size="xs" weight="semibold" className="truncate">
                    {`${name} ${share(top.session_share)}`}
                </Text>
                <Text render={<span />} size="xs" variant="muted" className="shrink-0 tabular-nums">
                    {others === 0
                        ? 'No other accounts'
                        : `${humanFriendlyLargeNumber(others)} ${others === 1 ? 'other' : 'others'} ${share(1 - top.session_share)}`}
                </Text>
            </div>
            <PartsBar parts={parts} unit="sessions" chartTooltip height={8} />
        </div>
    )
}
