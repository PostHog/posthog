import { useValues } from 'kea'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { selfDrivingSpendLogic } from '../../logics/selfDrivingSpendLogic'
import { RecordedSpend } from './RecordedSpend'

export function ScoutSpendLabel({ skillName }: { skillName?: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = selfDrivingSpendLogic({ teamId: currentTeamId ?? 0 })
    const { overview, spendByScout, failed } = useValues(logic)

    if (!overview && !failed) {
        return <LemonSkeleton className="h-3 w-32" />
    }
    if (failed) {
        return (
            <Tooltip title="Couldn't load usage. Refresh the page to try again.">
                <span className="text-xs text-muted">Usage unavailable</span>
            </Tooltip>
        )
    }
    return (
        <span className="inline-flex flex-wrap items-center gap-x-1 text-xs text-secondary" data-attr="scout-spend">
            <RecordedSpend
                spend={
                    skillName
                        ? (spendByScout.get(skillName) ?? { total_spend: 0, incomplete: false })
                        : overview?.scout_spend
                }
            />
            <span>usage · last 30 days</span>
        </span>
    )
}
