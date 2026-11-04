import clsx from 'clsx'
import { useValues } from 'kea'
import { useCallback } from 'react'

import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { INBOX_RANKING_SCORES, InboxRankingScore, rankingScoreForField } from '../../filterOptions'
import { captureInboxRankingDetailsViewed } from '../../inboxAnalytics'
import type { InboxRankingSortField } from '../../logics/inboxFiltersLogic'
import { SignalReport } from '../../types'
import { rankingPrediction } from '../../utils/reportOrdering'
import {
    formatRankingLift,
    formatRankingLiftComparison,
    formatRankingProbability,
    RANKING_STRENGTH_LABELS,
    RankingStrength,
    rankingStrength,
} from './rankingFormat'
import { RankingLiftBar } from './RankingLiftBar'

type Ranking = NonNullable<SignalReport['ranking']>

const STRENGTH_TAG_TYPES: Record<RankingStrength, LemonTagType> = {
    very_likely: 'success',
    likely: 'highlight',
    average: 'default',
    unlikely: 'muted',
}

function rankingLift(ranking: Ranking, outcome: string): number | null {
    const lift = rankingPrediction(ranking, outcome)?.lift
    return typeof lift === 'number' && Number.isFinite(lift) ? lift : null
}

/** The inbox shows raw probabilities and the model key to staff only. Other users see lifts alone. */
function rankingProbability(ranking: Ranking, outcome: string, isStaff: boolean): number | null {
    const probability = isStaff ? rankingPrediction(ranking, outcome)?.probability : undefined
    return typeof probability === 'number' ? probability : null
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
                <div>
                    <div className="text-sm font-semibold">We trained an ML model. Yay!</div>
                    <div className="opacity-70">How likely, compared with the average report</div>
                </div>
            )}
            <div className="flex flex-col gap-1">
                {scores.map((score) => {
                    const scoreLift = rankingLift(ranking, score.outcome)
                    const probability = rankingProbability(ranking, score.outcome, isStaff)
                    return (
                        <div key={score.outcome}>
                            <div className={clsx('flex items-center gap-2', score === active && 'font-bold')}>
                                <span className="w-16 shrink-0">{score.name}</span>
                                <span className="flex-1">
                                    <RankingLiftBar lift={scoreLift} />
                                </span>
                                <span className="w-9 shrink-0 text-right tabular-nums">
                                    {scoreLift !== null ? formatRankingLift(scoreLift) : null}
                                </span>
                                <span className="w-24 shrink-0 text-right whitespace-nowrap">
                                    {scoreLift !== null ? RANKING_STRENGTH_LABELS[rankingStrength(scoreLift)] : null}
                                </span>
                                {probability !== null && (
                                    <span className="w-10 shrink-0 text-right font-normal tabular-nums opacity-70">
                                        {formatRankingProbability(probability)}
                                    </span>
                                )}
                            </div>
                            {!active && (
                                <div className="opacity-70">{score.hoverCardDescription ?? score.description}</div>
                            )}
                        </div>
                    )
                })}
            </div>
            <div className="opacity-70">
                Very likely means 2x the average or more. Every report people open, act on or fix helps train the next
                version.
            </div>
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
