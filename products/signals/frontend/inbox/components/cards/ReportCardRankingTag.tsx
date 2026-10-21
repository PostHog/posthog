import clsx from 'clsx'
import { useCallback } from 'react'

import { LemonTag, LemonTagType, Tooltip } from '@posthog/lemon-ui'

import { INBOX_RANKING_SCORES, InboxRankingScore, rankingScoreForField } from '../../filterOptions'
import { captureInboxRankingDetailsViewed } from '../../inboxAnalytics'
import type { InboxRankingSortField } from '../../logics/inboxFiltersLogic'
import { SignalReport } from '../../types'
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

function rankingLift(ranking: Ranking, head: string): number | null {
    const lift = ranking.lifts?.[head]
    return typeof lift === 'number' && Number.isFinite(lift) ? lift : null
}

/** Raw probabilities and the model version come only to staff. Other users get lifts alone. */
function rankingProbability(ranking: Ranking, head: string): number | null {
    const probability = ranking.scores[head]
    return typeof probability === 'number' ? probability : null
}

function RankingHoverCard({ ranking, active }: { ranking: Ranking; active: InboxRankingScore }): JSX.Element {
    const lift = rankingLift(ranking, active.head)
    const others = INBOX_RANKING_SCORES.filter(
        (score) =>
            score !== active &&
            ranking.readable_heads.includes(score.head) &&
            (rankingLift(ranking, score.head) !== null || rankingProbability(ranking, score.head) !== null)
    )
    return (
        <div className="flex max-w-96 min-w-80 flex-col gap-2 text-xs">
            <div>
                <div className="font-semibold">
                    <span>{active.name}</span>:{' '}
                    <span>{lift !== null ? RANKING_STRENGTH_LABELS[rankingStrength(lift)] : 'no comparison'}</span>
                </div>
                <div className="opacity-70">{active.description}</div>
            </div>
            {lift !== null && (
                <div>
                    The model rates this report <span>{formatRankingLift(lift)}</span> as likely as the average report.
                </div>
            )}
            <div className="flex flex-col gap-1">
                {[active, ...others].map((score) => {
                    const scoreLift = rankingLift(ranking, score.head)
                    const probability = rankingProbability(ranking, score.head)
                    return (
                        <div
                            key={score.head}
                            className={clsx('flex items-center gap-2', score === active && 'font-bold')}
                        >
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
                    )
                })}
            </div>
            <div className="opacity-70">
                Very likely means 2x the average or more. The model estimates this from past reports.
            </div>
            {ranking.model_name && (
                <div className="border-t border-primary pt-1 font-mono opacity-70">
                    {ranking.model_name}@{ranking.model_version}
                </div>
            )}
        </div>
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
    const ranking = report.ranking
    const lift = ranking ? rankingLift(ranking, score.head) : null
    const probability = ranking ? rankingProbability(ranking, score.head) : null
    const state = !ranking || (lift === null && probability === null) ? 'unscored' : ranking.stale ? 'stale' : 'scored'
    const strength = lift !== null ? rankingStrength(lift) : null
    // Tooltip re-fires onOpen when the callback identity changes, so a new one each render would double count views.
    const onOpen = useCallback(
        (): void =>
            captureInboxRankingDetailsViewed({
                report,
                head: score.head,
                state,
                strength: state === 'scored' ? strength : null,
            }),
        [report, score.head, state, strength]
    )

    if (!ranking || state === 'unscored') {
        return (
            <Tooltip
                title="The model has not scored this report yet. Until it does, the report sorts after the scored ones."
                onOpen={onOpen}
            >
                <LemonTag size="small" type="muted" className="cursor-help" data-attr="inbox-ranking-tag">
                    Not scored yet
                </LemonTag>
            </Tooltip>
        )
    }
    if (state === 'stale') {
        return (
            <Tooltip
                title="The title or summary changed after the model scored this report. Until the model scores it again, it sorts after the scored ones."
                onOpen={onOpen}
            >
                <LemonTag size="small" type="muted" className="cursor-help" data-attr="inbox-ranking-tag">
                    Score out of date
                </LemonTag>
            </Tooltip>
        )
    }
    return (
        <Tooltip title={<RankingHoverCard ranking={ranking} active={score} />} onOpen={onOpen} openOnClick>
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
