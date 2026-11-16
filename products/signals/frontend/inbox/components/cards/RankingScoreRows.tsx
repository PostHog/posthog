import clsx from 'clsx'

import { InboxRankingScore } from '../../filterOptions'
import { SignalReport } from '../../types'
import { rankingLift, rankingProbability } from '../../utils/reportOrdering'
import { formatRankingLift, formatRankingProbability, RANKING_STRENGTH_LABELS, rankingStrength } from './rankingFormat'
import { RankingLiftBar } from './RankingLiftBar'

/**
 * One row per score: its lift bar, lift and strength, plus the raw probability for staff. Without an
 * active head, each row also carries its description, because nothing above the rows explains them.
 */
export function RankingScoreRows({
    ranking,
    scores,
    active,
    isStaff,
}: {
    ranking: NonNullable<SignalReport['ranking']>
    scores: InboxRankingScore[]
    active: InboxRankingScore | null
    isStaff: boolean
}): JSX.Element {
    return (
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
                        {!active && <div className="opacity-70">{score.hoverCardDescription ?? score.description}</div>}
                    </div>
                )
            })}
        </div>
    )
}
