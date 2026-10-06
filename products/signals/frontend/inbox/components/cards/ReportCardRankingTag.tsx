import clsx from 'clsx'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { RANKING_HEAD_LABELS, RANKING_SORT_HEADS } from '../../filterOptions'
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
    head,
}: {
    ranking: NonNullable<SignalReport['ranking']>
    head: string
}): JSX.Element {
    const heads = [head, ...ranking.readable_heads.filter((name) => name !== head)].filter(
        (name) => typeof ranking.scores[name] === 'number'
    )
    return (
        <div className="flex min-w-72 flex-col gap-1 text-xs">
            {heads.map((name) => {
                const probability = ranking.scores[name]
                const lift = rankingLift(ranking, name)
                return (
                    <div key={name} className={clsx('flex items-center gap-2', name === head && 'font-bold')}>
                        <span className="w-28 shrink-0">{RANKING_HEAD_LABELS[name] ?? name}</span>
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

/** The active model sort's lift for one report, in the card's meta row. Falls back to the probability when the head has no lift. */
export function ReportCardRankingTag({
    report,
    sortField,
}: {
    report: SignalReport
    sortField: InboxRankingSortField
}): JSX.Element {
    const { head, tagLabel } = RANKING_SORT_HEADS[sortField]
    const probability = report.ranking?.scores[head]
    const lift = report.ranking ? rankingLift(report.ranking, head) : null
    if (!report.ranking || typeof probability !== 'number') {
        return (
            <LemonTag size="small" type="muted" data-attr="inbox-ranking-tag">
                Not scored
            </LemonTag>
        )
    }
    return (
        <Tooltip title={<RankingTooltip ranking={report.ranking} head={head} />}>
            <LemonTag size="small" className="cursor-help tabular-nums" data-attr="inbox-ranking-tag">
                {lift !== null ? formatRankingLift(lift) : formatRankingProbability(probability)} {tagLabel}
            </LemonTag>
        </Tooltip>
    )
}
