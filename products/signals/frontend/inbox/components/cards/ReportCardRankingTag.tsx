import { useValues } from 'kea'
import { useCallback } from 'react'

import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { INBOX_RANKING_SCORES, InboxRankingScore, rankingScoreForField } from '../../filterOptions'
import { captureInboxRankingDetailsViewed } from '../../inboxAnalytics'
import type { InboxRankingSortField } from '../../logics/inboxFiltersLogic'
import { SignalReport } from '../../types'
import { rankingLift, rankingPrediction, rankingProbability } from '../../utils/reportOrdering'
import {
    formatRankingLift,
    formatRankingLiftComparison,
    formatRankingProbability,
    RANKING_STRENGTH_LABELS,
    RankingStrength,
    rankingStrength,
} from './rankingFormat'
import { RankingModelHeader } from './RankingModelHeader'
import { RankingScaleNote } from './RankingScaleNote'
import { RankingScoreRows } from './RankingScoreRows'

type Ranking = NonNullable<SignalReport['ranking']>

const STRENGTH_TAG_TYPES: Record<RankingStrength, LemonTagType> = {
    very_likely: 'success',
    likely: 'highlight',
    average: 'default',
    unlikely: 'muted',
}

/**
 * The score details. With an active head, it leads with that head and lists the other readable heads.
 * Without one, as on the Recommended pill, it lists all three heads in funnel order with their descriptions.
 */
export function RankingHoverCard({
    ranking,
    active,
    isStaff,
}: {
    ranking: Ranking
    active: InboxRankingScore | null
    isStaff: boolean
}): JSX.Element {
    const lift = active ? rankingLift(ranking, active.outcome) : null
    const scores = active
        ? [
              active,
              ...INBOX_RANKING_SCORES.filter(
                  (score) =>
                      score !== active &&
                      rankingPrediction(ranking, score.outcome)?.readable &&
                      (rankingLift(ranking, score.outcome) !== null ||
                          rankingProbability(ranking, score.outcome, isStaff) !== null)
              ),
          ]
        : INBOX_RANKING_SCORES
    return (
        <div className="flex max-w-96 min-w-80 flex-col gap-2 text-xs">
            {active ? (
                <>
                    <div>
                        <div className="font-semibold">
                            <span>{active.name}</span>:{' '}
                            <span>
                                {lift !== null ? RANKING_STRENGTH_LABELS[rankingStrength(lift)] : 'no comparison'}
                            </span>
                        </div>
                        <div className="opacity-70">{active.hoverCardDescription ?? active.description}</div>
                    </div>
                    {lift !== null && (
                        <div>
                            The model rates this report <span>{formatRankingLift(lift)}</span> as likely as the average
                            report.
                        </div>
                    )}
                </>
            ) : (
                <RankingModelHeader />
            )}
            <RankingScoreRows ranking={ranking} scores={scores} active={active} isStaff={isStaff} />
            <RankingScaleNote />
            {!active && (
                <div className="opacity-70">
                    Here to help you find the good stuff faster. Your agent gets these too, through the inbox MCP tools.
                </div>
            )}
            {isStaff && ranking.model && (
                <div className="border-t border-primary pt-1 font-mono opacity-70">{ranking.model}</div>
            )}
        </div>
    )
}

/** The muted tag for a report the model has not scored yet, or scored before its last edit. Score sorts put it after the scored ones. */
export function RankingStatusTag({ state, onOpen }: { state: 'stale' | 'unscored'; onOpen: () => void }): JSX.Element {
    return (
        <Tooltip
            title={
                state === 'stale'
                    ? 'The title or summary changed after the model scored this report. Until the model scores it again, it sorts after the scored ones.'
                    : 'The model has not scored this report yet. Until it does, the report sorts after the scored ones.'
            }
            onOpen={onOpen}
        >
            <LemonTag size="small" type="muted" className="cursor-help" data-attr="inbox-ranking-tag">
                {state === 'stale' ? 'Score out of date' : 'Not scored yet'}
            </LemonTag>
        </Tooltip>
    )
}

/**
 * How likely the report is to reach the active model sort's outcome, in the card's meta row. A report
 * edited after it was scored, or not scored yet, says so, because the model sort puts it after the scored ones.
 */
export function ReportCardRankingTag({
    report,
    sortField,
}: {
    report: SignalReport
    sortField: InboxRankingSortField
}): JSX.Element {
    const score = rankingScoreForField(sortField)
    const isStaff = useValues(userLogic).user?.is_staff ?? false
    const ranking = report.ranking
    const lift = ranking ? rankingLift(ranking, score.outcome) : null
    const probability = ranking ? rankingProbability(ranking, score.outcome, isStaff) : null
    const state =
        !ranking ||
        ranking.status === 'unscored' ||
        ranking.status === 'not_available' ||
        (lift === null && probability === null)
            ? 'unscored'
            : ranking.status === 'stale'
              ? 'stale'
              : 'scored'
    const strength = lift !== null ? rankingStrength(lift) : null
    // Tooltip re-fires onOpen when the callback identity changes, so a new one each render would double count views.
    const onOpen = useCallback(
        (): void =>
            captureInboxRankingDetailsViewed({
                report,
                surface: 'tag',
                head: score.head,
                state,
                strength: state === 'scored' ? strength : null,
            }),
        [report, score.head, state, strength]
    )

    if (!ranking || state !== 'scored') {
        return <RankingStatusTag state={state === 'stale' ? 'stale' : 'unscored'} onOpen={onOpen} />
    }
    return (
        <Tooltip
            title={<RankingHoverCard ranking={ranking} active={score} isStaff={isStaff} />}
            onOpen={onOpen}
            openOnClick
        >
            <LemonTag
                size="small"
                type={strength ? STRENGTH_TAG_TYPES[strength] : 'default'}
                className="cursor-help tabular-nums"
                data-attr="inbox-ranking-tag"
                // The card is a link. A tap on the pill opens the details instead of the report.
                onClick={(event) => {
                    event.preventDefault()
                    event.stopPropagation()
                }}
            >
                {lift !== null
                    ? formatRankingLiftComparison(lift)
                    : `${formatRankingProbability(probability ?? 0)} ${score.tagLabel}`}
            </LemonTag>
        </Tooltip>
    )
}
