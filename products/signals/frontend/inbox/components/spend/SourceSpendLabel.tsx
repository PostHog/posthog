import { useValues } from 'kea'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { sourceSpendLogic } from '../../logics/sourceSpendLogic'
import { RecordedSpend } from './RecordedSpend'

export function SourceSpendLabel({ sourceProduct }: { sourceProduct: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const { sources, failed, spendByProduct } = useValues(sourceSpendLogic({ teamId: currentTeamId ?? 0 }))

    if (failed) {
        return (
            <Tooltip title="Couldn't load source usage. Refresh the page to try again.">
                <span className="text-xs text-muted">Unavailable</span>
            </Tooltip>
        )
    }
    if (sources === null) {
        return <LemonSkeleton className="h-3 w-10" />
    }
    const amount = spendByProduct.get(sourceProduct)
    return (
        <span className="shrink-0 whitespace-nowrap text-xs text-muted" data-attr="source-spend">
            <RecordedSpend
                amount={amount === undefined ? 0 : amount}
                description="Accumulated processing usage for signals received in the last 30 days, including later research."
            />
        </span>
    )
}
