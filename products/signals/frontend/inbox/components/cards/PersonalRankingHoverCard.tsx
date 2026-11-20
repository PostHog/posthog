import { INBOX_PERSONAL_TIERS, INBOX_RANKING_SCORES } from '../../filterOptions'
import { SignalReport } from '../../types'
import { RankingModelHeader } from './RankingModelHeader'
import { RankingScaleNote } from './RankingScaleNote'
import { RankingScoreRows } from './RankingScoreRows'
import { RankingStaffFooter } from './ReportCardRankingTag'

/**
 * The score details on the personal order. It leads with whether the report is on the user's own
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
    return (
        <div className="flex max-w-96 min-w-80 flex-col gap-2 text-xs">
            {tier !== null ? (
                <div>
                    <div className="text-sm font-semibold">
                        <span>On your list</span>
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
            {isStaff && <RankingStaffFooter ranking={ranking} />}
        </div>
    )
}
