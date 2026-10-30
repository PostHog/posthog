import { useValues } from 'kea'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { selfDrivingSpendLogic } from '../../logics/selfDrivingSpendLogic'
import { RecordedSpend } from './RecordedSpend'

export function ScoutSpendLabel({
    skillName,
    average = false,
}: {
    skillName: string
    average?: boolean
}): JSX.Element | null {
    const { currentTeamId } = useValues(teamLogic)
    const logic = selfDrivingSpendLogic({ teamId: currentTeamId ?? 0 })
    const { overview, spendByScout, averageSpendByScout, failed } = useValues(logic)

    if (failed) {
        return (
            <Tooltip title="Couldn't load usage. Refresh the page to try again.">
                <span className="text-xs text-muted">Usage unavailable</span>
            </Tooltip>
        )
    }
    if (!overview) {
        return <LemonSkeleton className="h-3 w-32" />
    }
    if (average && !averageSpendByScout.has(skillName)) {
        return null
    }
    const amount = (average ? averageSpendByScout : spendByScout).get(skillName)
    return (
        <span className="inline-flex flex-wrap items-center gap-x-1 text-xs text-secondary" data-attr="scout-spend">
            <RecordedSpend
                amount={amount === undefined ? (average ? null : 0) : amount}
                description={
                    average ? 'Average usage across runs with recorded amounts in the last 30 days.' : undefined
                }
            />
            <span>{average ? 'avg per run · last 30 days' : 'usage · last 30 days'}</span>
        </span>
    )
}
