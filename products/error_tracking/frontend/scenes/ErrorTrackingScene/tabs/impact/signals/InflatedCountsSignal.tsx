import { useMemo } from 'react'

import { IconClock } from '@posthog/icons'

import { Text, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import type { InflatedCountsIssue } from '../../recommendations/types'
import { share } from '../impactFormat'
import { type Part, PartsBar } from './PartsBar'
import { SignalHeadline } from './SignalHeadline'
import { fade, useImpactPalette } from './useImpactPalette'

function headline(issue: InflatedCountsIssue): { value: string; caption: string } {
    if (issue.reasons.includes('top_session')) {
        return { value: share(issue.top_session_share), caption: 'of events from one session' }
    }
    if (issue.reasons.includes('heavy_sessions')) {
        return { value: share(issue.heavy_session_share), caption: 'of events from sessions with 50+' }
    }
    return { value: String(issue.timer_sessions), caption: 'sessions repeat it on a timer' }
}

// A part-to-whole bar of the issue's events: one session, other sessions with 50 or more events, and everyone else.
export function InflatedCountsSignal({ issue }: { issue: InflatedCountsIssue }): JSX.Element {
    const palette = useImpactPalette()
    const { value, caption } = headline(issue)
    const parts = useMemo<Part[]>(() => {
        const otherHeavyShare = Math.max(issue.heavy_session_share - issue.top_session_share, 0)
        const restShare = Math.max(1 - issue.top_session_share - otherHeavyShare, 0)
        return [
            {
                key: 'top',
                label: 'One session',
                value: issue.top_session_share * issue.occurrences,
                color: palette.noise,
            },
            {
                key: 'heavy',
                label: 'Other sessions with 50+ events',
                value: otherHeavyShare * issue.occurrences,
                color: fade(palette.noise, 0.45),
            },
            { key: 'rest', label: 'All other sessions', value: restShare * issue.occurrences, color: palette.neutral },
        ]
    }, [issue, palette])

    return (
        <Tooltip>
            <TooltipTrigger render={<div tabIndex={0} className="flex w-full max-w-64 flex-col gap-1.5" />}>
                <SignalHeadline value={value} caption={caption} />
                <PartsBar parts={parts} unit="events" chartTooltip={false} />
                {issue.timer_interval_seconds !== null && (
                    <div className="flex items-center gap-1 text-muted-foreground">
                        <IconClock className="size-3.5 shrink-0" />
                        <Text render={<span />} size="xs" variant="muted">
                            {`Repeats every ${issue.timer_interval_seconds}s`}
                        </Text>
                    </div>
                )}
            </TooltipTrigger>
            <TooltipContent>
                {`${humanFriendlyLargeNumber(issue.occurrences)} events from ${humanFriendlyLargeNumber(issue.sessions)} sessions. One session produced ${share(issue.top_session_share)} of them, and sessions with 50 or more events produced ${share(issue.heavy_session_share)}.`}
            </TooltipContent>
        </Tooltip>
    )
}
