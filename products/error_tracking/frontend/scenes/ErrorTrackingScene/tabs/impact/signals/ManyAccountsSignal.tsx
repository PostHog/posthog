import { useMemo } from 'react'

import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { ManyAccountsIssue } from '../../recommendations/types'
import { share } from '../impactFormat'
import { type Part, PartsBar } from './PartsBar'
import { SignalHeadline } from './SignalHeadline'
import { useImpactPalette } from './useImpactPalette'

// How many accounts the issue reached, with a bar for their share of all active accounts.
export function ManyAccountsSignal({
    issue,
    groupLabel,
}: {
    issue: ManyAccountsIssue
    groupLabel: string
}): JSX.Element {
    const palette = useImpactPalette()
    const parts = useMemo<Part[]>(() => {
        const active = issue.account_share > 0 ? issue.accounts / issue.account_share : issue.accounts
        return [
            { key: 'reached', label: 'Reached', value: issue.accounts, color: palette.audience },
            { key: 'rest', label: 'Not reached', value: Math.max(active - issue.accounts, 0), color: palette.neutral },
        ]
    }, [issue, palette])
    return (
        <div className="flex w-full max-w-64 flex-col gap-1.5">
            <SignalHeadline
                value={humanFriendlyLargeNumber(issue.accounts)}
                caption={`${groupLabel}, ${share(issue.account_share)} of active`}
            />
            <PartsBar parts={parts} unit={groupLabel} chartTooltip />
        </div>
    )
}
