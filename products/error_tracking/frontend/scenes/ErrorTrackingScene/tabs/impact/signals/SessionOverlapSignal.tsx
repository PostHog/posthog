import { useMemo } from 'react'

import { Text } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { RelatedIssuesIssue } from '../../recommendations/types'
import { type Part, PartsBar } from './PartsBar'
import { fade, useImpactPalette } from './useImpactPalette'

// All sessions with either issue, split into only this issue, both issues at any time, and only the other. The
// middle part is the relationship.
export function SessionOverlapSignal({ pair }: { pair: RelatedIssuesIssue }): JSX.Element {
    const palette = useImpactPalette()
    const both = pair.both_sessions
    const onlyThis = Math.max(pair.sessions - both, 0)
    const onlyOther = Math.max(pair.related_sessions - both, 0)
    const parts = useMemo<Part[]>(
        () => [
            { key: 'this', label: 'Only this issue', value: onlyThis, color: fade(palette.related, 0.4) },
            { key: 'both', label: 'Both issues', value: both, color: palette.related },
            { key: 'other', label: 'Only the related issue', value: onlyOther, color: fade(palette.related, 0.4) },
        ],
        [onlyThis, both, onlyOther, palette]
    )
    return (
        <div className="flex w-full max-w-64 flex-col gap-1">
            <PartsBar parts={parts} unit="sessions" chartTooltip />
            <div className="flex justify-between gap-2">
                <Text render={<span />} size="xs" variant="muted" className="tabular-nums">
                    {`only this ${humanFriendlyLargeNumber(onlyThis)}`}
                </Text>
                <Text render={<span />} size="xs" weight="semibold" className="tabular-nums">
                    {`both ${humanFriendlyLargeNumber(both)}`}
                </Text>
                <Text render={<span />} size="xs" variant="muted" className="tabular-nums">
                    {`only other ${humanFriendlyLargeNumber(onlyOther)}`}
                </Text>
            </div>
        </div>
    )
}
