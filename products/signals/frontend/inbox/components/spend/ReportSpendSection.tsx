import { useActions, useValues } from 'kea'

import { IconReceipt } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { reportSpendLogic } from '../../logics/reportSpendLogic'
import { DetailSection } from '../detail/DetailSection'
import { RecordedSpend } from './RecordedSpend'

export function ReportSpendSection({ reportId }: { reportId: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = reportSpendLogic({ teamId: currentTeamId ?? 0, reportId })
    const { spend, spendLoading, failed } = useValues(logic)
    const { refreshSpend } = useActions(logic)

    return (
        <DetailSection title="Usage" icon={<IconReceipt />}>
            {failed ? (
                <LemonBanner
                    type="error"
                    action={
                        <LemonButton onClick={() => refreshSpend()} loading={spendLoading}>
                            Retry
                        </LemonButton>
                    }
                >
                    Couldn't load usage.
                </LemonBanner>
            ) : !spend ? (
                <LemonSkeleton className="h-8 w-full" />
            ) : (
                <div className="flex flex-col gap-2 text-xs" data-attr="report-spend">
                    <div className="flex flex-wrap justify-between gap-2">
                        <span>Report generation</span>
                        <RecordedSpend amount={spend.generation.total_spend} />
                    </div>
                    {spend.implementation.total_spend !== null && (
                        <div className="flex flex-wrap justify-between gap-2">
                            <span>Implementation</span>
                            <RecordedSpend amount={spend.implementation.total_spend} />
                        </div>
                    )}
                    {spend.shared_scout_runs.total_spend !== null && (
                        <div className="flex flex-col gap-1">
                            <div className="flex flex-wrap justify-between gap-2">
                                <span>Authoring scout runs</span>
                                <RecordedSpend amount={spend.shared_scout_runs.total_spend} />
                            </div>
                            <span className="text-muted">Shared across all output of these runs.</span>
                        </div>
                    )}
                </div>
            )}
        </DetailSection>
    )
}
