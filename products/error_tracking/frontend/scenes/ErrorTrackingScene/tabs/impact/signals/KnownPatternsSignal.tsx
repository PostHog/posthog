import { useMemo } from 'react'

import { Text, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import type { KnownPatternsIssue, KnownPatternsRecommendationMeta } from '../../recommendations/types'
import { KNOWN_PATTERN_LABELS, share } from '../impactFormat'
import { type Part, PartsBar } from './PartsBar'
import { fade, useImpactPalette } from './useImpactPalette'

export interface KnownPatternsSignalProps {
    issue: KnownPatternsIssue
    totalEvents: number
    classes: KnownPatternsRecommendationMeta['classes']
}

type NoiseReason = KnownPatternsIssue['reasons'][number]

// The reason a signal explains when an issue has several, from the most specific to the most general.
const REASON_ORDER: NoiseReason[] = ['known_pattern', 'third_party', 'app_reported', 'no_own_code']

const REASON_LABELS: Record<Exclude<NoiseReason, 'known_pattern'>, string> = {
    third_party: 'Third-party script',
    app_reported: 'Reported by your app',
    no_own_code: 'Outside your code',
}

// The stacks or events behind a reason other than a known pattern, as a share against the rest.
function reasonParts(
    reason: Exclude<NoiseReason, 'known_pattern'>,
    issue: KnownPatternsIssue,
    colors: { noise: string; neutral: string }
): Part[] {
    const [share, label, rest] =
        reason === 'third_party'
            ? [issue.third_party_share, 'Starts in a third-party script', 'Starts in your code']
            : reason === 'app_reported'
              ? [issue.handled_share ?? 0, 'Caught and reported by your app', 'Not caught']
              : [1 - (issue.own_code_share ?? 0), 'Never reaches your code', 'Reaches your code']
    return [
        { key: 'noise', label, value: share, color: colors.noise },
        { key: 'rest', label: rest, value: 1 - share, color: colors.neutral },
    ]
}

function reasonTooltip(reason: NoiseReason, label: string, issue: KnownPatternsIssue): string {
    switch (reason) {
        case 'known_pattern':
            return `This issue matches the ${label} pattern, which is usually noise. The bar splits all your web error events by pattern, with this one highlighted.`
        case 'third_party':
            return `The innermost frame of this issue's stack is in a third-party script, not resolved through your source maps, in ${share(issue.third_party_share)} of events, so your code may not be the cause.`
        case 'app_reported':
            return `Your app caught this error and reported it as a plain Error with a sentence for a message, such as a failed request or a permission check. That is an expected failure, not a crash.`
        case 'no_own_code':
            return `In ${share(1 - (issue.own_code_share ?? 0))} of events, the stack has no frame in your own code: there is no stack, or only frames from dependencies. There is no line in your code to fix.`
    }
}

// For a known pattern, the project's error volume split by pattern with this issue's pattern lit up, so a noisy
// pattern that is a third of everything is obvious at a glance. For the other reasons, the share of the issue's events
// behind the reason.
export function KnownPatternsSignal({ issue, totalEvents, classes }: KnownPatternsSignalProps): JSX.Element {
    const palette = useImpactPalette()
    const reason = REASON_ORDER.find((candidate) => issue.reasons.includes(candidate)) ?? 'known_pattern'
    const label = reason === 'known_pattern' ? KNOWN_PATTERN_LABELS[issue.pattern] : REASON_LABELS[reason]
    const parts = useMemo<Part[]>(
        () =>
            reason === 'known_pattern'
                ? classes.map((entry) => ({
                      key: entry.pattern,
                      label: KNOWN_PATTERN_LABELS[entry.pattern],
                      value: entry.events,
                      color: entry.pattern === issue.pattern ? palette.noise : fade(palette.ink, 0.18),
                  }))
                : reasonParts(reason, issue, { noise: palette.noise, neutral: palette.neutral }),
        [reason, classes, issue, palette]
    )
    const summary =
        reason === 'known_pattern'
            ? `${share(totalEvents > 0 ? issue.events / totalEvents : 0)} of all errors`
            : `${share(parts[0].value)} of events`
    return (
        <Tooltip>
            <TooltipTrigger render={<div tabIndex={0} className="flex w-full max-w-64 flex-col gap-1.5" />}>
                <div className="flex min-w-0 items-baseline justify-between gap-2">
                    <Text render={<span />} size="xs" weight="semibold" className="truncate">
                        {label}
                    </Text>
                    <Text render={<span />} size="xs" variant="muted" className="shrink-0 tabular-nums">
                        {summary}
                    </Text>
                </div>
                <PartsBar
                    parts={parts}
                    unit={reason === 'known_pattern' ? 'events' : 'of events'}
                    chartTooltip={false}
                    height={8}
                />
            </TooltipTrigger>
            <TooltipContent>{reasonTooltip(reason, label, issue)}</TooltipContent>
        </Tooltip>
    )
}
