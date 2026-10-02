import clsx from 'clsx'

import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { RANKING_HEAD_LABELS, RANKING_SORT_HEADS } from '../../filterOptions'
import type { InboxRankingSortField } from '../../logics/inboxFiltersLogic'
import { SignalReport } from '../../types'

/** No decimals at 10% and above. Heads such as `action` have low base rates, so one decimal below 10%. */
export function formatRankingProbability(probability: number): string {
    const percent = probability * 100
    const oneDecimal = Math.round(percent * 10) / 10
    return oneDecimal >= 10 ? `${Math.round(percent)}%` : `${oneDecimal.toFixed(1)}%`
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
        <div className="flex min-w-56 flex-col gap-1 text-xs">
            {heads.map((name) => {
                const probability = ranking.scores[name]
                return (
                    <div key={name} className={clsx('flex items-center gap-2', name === head && 'font-bold')}>
                        <span className="w-28 shrink-0">{RANKING_HEAD_LABELS[name] ?? name}</span>
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-fill-tertiary">
                            <span
                                className="block h-full rounded-full bg-current"
                                // oxlint-disable-next-line react/forbid-dom-props
                                style={{ width: `${Math.round(probability * 100)}%` }}
                            />
                        </span>
                        <span className="w-10 shrink-0 text-right tabular-nums">
                            {formatRankingProbability(probability)}
                        </span>
                    </div>
                )
            })}
            <div className="mt-1 border-t border-primary pt-1 font-mono text-muted">
                {ranking.model_name}@{ranking.model_version}
            </div>
        </div>
    )
}

/** The active model sort's probability for one report, in the card's meta row. */
export function ReportCardRankingTag({
    report,
    sortField,
}: {
    report: SignalReport
    sortField: InboxRankingSortField
}): JSX.Element {
    const { head, tagLabel } = RANKING_SORT_HEADS[sortField]
    const probability = report.ranking?.scores[head]
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
                {formatRankingProbability(probability)} {tagLabel}
            </LemonTag>
        </Tooltip>
    )
}
