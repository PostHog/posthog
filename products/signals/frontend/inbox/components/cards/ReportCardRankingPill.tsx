import { useValues } from 'kea'
import { useCallback } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { INBOX_RANKING_SCORES } from '../../filterOptions'
import { captureInboxRankingDetailsViewed } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { RankingPillLifts, rankingPillLifts } from '../../utils/reportOrdering'
import { PersonalRankingHoverCard } from './PersonalRankingHoverCard'
import { formatRankingLift, RankingStrength, rankingStrength } from './rankingFormat'
import { RankingHoverCard, RankingStatusTag } from './ReportCardRankingTag'

// A strong value is bold too, so color is not the only signal.
const STRENGTH_VALUE_CLASSES: Record<RankingStrength, string> = {
    very_likely: 'font-bold text-success',
    likely: 'font-semibold text-accent',
    average: 'text-secondary',
    unlikely: 'text-muted',
}

/**
 * The three ranking scores in funnel order, in the card's meta row on the Recommended and Personalized
 * sorts. The chip stays neutral and each value takes the color of its own strength. A stale or unscored
 * report keeps the muted tag that the score sorts show. On the Personalized sort the hover card leads
 * with the report's place on the user's own list.
 */
export function ReportCardRankingPill({
    report,
    personalSort = false,
}: {
    report: SignalReport
    personalSort?: boolean
}): JSX.Element {
    const isStaff = useValues(userLogic).user?.is_staff ?? false
    const lifts = rankingPillLifts(report)
    const state = lifts ? 'scored' : report.ranking?.status === 'stale' ? 'stale' : 'unscored'
    const personalTier = personalSort ? (report.personal_tier ?? null) : null
    // Tooltip re-fires onOpen when the callback identity changes, so a new one each render would double count views.
    const onOpen = useCallback(
        (): void =>
            captureInboxRankingDetailsViewed({
                report,
                surface: 'pill',
                head: null,
                state,
                strength: null,
                personalTier,
            }),
        [report, state, personalTier]
    )
    if (!lifts || !report.ranking) {
        return <RankingStatusTag state={state === 'stale' ? 'stale' : 'unscored'} onOpen={onOpen} />
    }
    return (
        <Tooltip
            title={
                personalSort ? (
                    <PersonalRankingHoverCard report={report} ranking={report.ranking} isStaff={isStaff} />
                ) : (
                    <RankingHoverCard ranking={report.ranking} active={null} isStaff={isStaff} />
                )
            }
            onOpen={onOpen}
            openOnClick
        >
            <button
                type="button"
                className="inline-flex max-w-full cursor-help items-stretch divide-x divide-primary overflow-hidden rounded border border-primary bg-surface-primary text-xs leading-none text-secondary tabular-nums"
                data-attr="inbox-ranking-pill"
                // The card is a link. A tap on the pill opens the details instead of the report.
                onClick={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                }}
            >
                {INBOX_RANKING_SCORES.map((score) => {
                    const lift = lifts[score.outcome as keyof RankingPillLifts]
                    return (
                        <span key={score.outcome} className="flex items-center gap-1 px-1.5 py-1 whitespace-nowrap">
                            <span>{score.name}</span>
                            <span className={lift !== null ? STRENGTH_VALUE_CLASSES[rankingStrength(lift)] : ''}>
                                {lift !== null ? formatRankingLift(lift) : '–'}
                            </span>
                        </span>
                    )
                })}
            </button>
        </Tooltip>
    )
}
