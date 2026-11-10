import { INBOX_PERSONAL_TIERS, INBOX_RANKING_SCORES } from '../../filterOptions'
import { SignalReport } from '../../types'
import { RankingModelHeader } from './RankingModelHeader'
import { RankingScaleNote } from './RankingScaleNote'
import { RankingScoreRows } from './RankingScoreRows'

/**
 * The score details on the Personalized sort. It leads with where the report sits on the user's own
 * list, then shows the same model section as the Recommended card, because the scores are the same
 * for everyone on the team.
 */
export function PersonalRankingHoverCard({
    report,
    ranking,
    isStaff,
}: {
    report: SignalReport
    ranking: NonNullable<SignalReport['ranking']>
    isStaff: boolean
}): JSX.Element {
    const tier = report.personal_tier
        ? (INBOX_PERSONAL_TIERS[report.personal_tier]?.label ?? report.personal_tier)
        : null
    // The server sends a listed report's position from 0 as its merge key.
    const rank = tier !== null && typeof report.inbox_merge_key === 'number' ? report.inbox_merge_key + 1 : null
    return (
        <div className="flex max-w-96 min-w-80 flex-col gap-2 text-xs">
            {tier !== null ? (
                <div>
                    <div className="text-sm font-semibold">
                        <span>{rank !== null ? `#${rank} on your list` : 'On your list'}</span>
                        <span className="font-normal opacity-70">{` · ${tier}`}</span>
                    </div>
                    {report.personal_reason && <div>{report.personal_reason}</div>}
                </div>
            ) : (
                <div>Not on your list. This report comes after your list, in Recommended order.</div>
            )}
            <div className="border-t border-primary pt-2">
                <RankingModelHeader note="Same for everyone on the team." />
            </div>
            <RankingScoreRows ranking={ranking} scores={INBOX_RANKING_SCORES} active={null} isStaff={isStaff} />
            <RankingScaleNote />
            <div className="opacity-70">
                Your list is built from your recent activity in PostHog and these scores. It refreshes every few hours.
            </div>
            {isStaff && ranking.model && (
                <div className="border-t border-primary pt-1 font-mono opacity-70">{ranking.model}</div>
            )}
        </div>
    )
}
