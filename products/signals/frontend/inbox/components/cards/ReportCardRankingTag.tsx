import clsx from 'clsx'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { INBOX_RANKING_SCORES, InboxRankingScore, rankingScoreForField } from '../../filterOptions'
import type { InboxRankingSortField } from '../../logics/inboxFiltersLogic'
import { SignalReport } from '../../types'
import { formatRankingLift, formatRankingProbability } from './rankingFormat'
import { RankingLiftBar } from './RankingLiftBar'

function rankingLift(ranking: NonNullable<SignalReport['ranking']>, head: string): number | null {
    const lift = ranking.lifts?.[head]
    return typeof lift === 'number' && Number.isFinite(lift) ? lift : null
}

function RankingTooltip({
    ranking,
    active,
}: {
    ranking: NonNullable<SignalReport['ranking']>
    active: InboxRankingScore
}): JSX.Element {
    const scores = [active, ...INBOX_RANKING_SCORES.filter((score) => score !== active)].filter(
        (score) =>
            typeof ranking.scores[score.head] === 'number' &&
            (score === active || ranking.readable_heads.includes(score.head))
    )
    return (
        <div className="flex min-w-72 flex-col gap-1 text-xs">
            {scores.map((score) => {
                const probability = ranking.scores[score.head]
                const lift = rankingLift(ranking, score.head)
                return (
                    <div key={score.head} className={clsx('flex items-center gap-2', score === active && 'font-bold')}>
                        <span className="w-28 shrink-0">{score.name}</span>
                        <span className="flex-1">
                            <RankingLiftBar lift={lift} />
                        </span>
                        <span className="w-10 shrink-0 text-right tabular-nums">
                            {lift !== null ? formatRankingLift(lift) : null}
                        </span>
                        <span className="w-10 shrink-0 text-right font-normal tabular-nums opacity-70">
                            {formatRankingProbability(probability)}
                        </span>
                    </div>
                )
            })}
            <div className="opacity-70">Compared with the average report</div>
            <div className="mt-1 border-t border-primary pt-1 font-mono opacity-70">
                {ranking.model_name}@{ranking.model_version}
            </div>
        </div>
    )
}

/** The active model sort's lift for one report, in the card's meta row. Falls back to the probability when the head has no lift, and shows no score when the report was edited after it was scored. */
export function ReportCardRankingTag({
    report,
    sortField,
}: {
    report: SignalReport
    sortField: InboxRankingSortField
}): JSX.Element {
    const score = rankingScoreForField(sortField)
    const { head, tagLabel } = score
    const probability = report.ranking?.scores[head]
    const lift = report.ranking ? rankingLift(report.ranking, head) : null
    if (!report.ranking || typeof probability !== 'number') {
        return (
            <LemonTag size="small" type="muted" data-attr="inbox-ranking-tag">
                Not scored
            </LemonTag>
        )
    }
    if (report.ranking.stale) {
        return (
            <Tooltip title="The title or summary changed after this report was scored, so the score describes the old text.">
                <LemonTag size="small" type="muted" className="cursor-help" data-attr="inbox-ranking-tag">
                    Edited since scored
                </LemonTag>
            </Tooltip>
        )
    }
    return (
        <Tooltip title={<RankingTooltip ranking={report.ranking} active={score} />}>
            <LemonTag size="small" className="cursor-help tabular-nums" data-attr="inbox-ranking-tag">
                {lift !== null ? formatRankingLift(lift) : formatRankingProbability(probability)} {tagLabel}
            </LemonTag>
        </Tooltip>
    )
}
