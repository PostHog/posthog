import { useActions, useValues } from 'kea'

import { IconReceipt } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import type { ReportSpendApi } from 'products/signals/frontend/generated/api.schemas'

import { reportSpendLogic } from '../../logics/reportSpendLogic'
import { DetailSection } from '../detail/DetailSection'
import { RecordedSpend } from './RecordedSpend'

// Scout runs are shared with the rest of their output, so they stay out of this report's total.
function reportOwnSpend({ generation, implementation }: ReportSpendApi): number | null {
    if (generation.total_spend === null && implementation.total_spend === null) {
        return null
    }
    return (generation.total_spend ?? 0) + (implementation.total_spend ?? 0)
}

// A scout that authors a report directly skips the generation stage, so it has no generation receipts to miss.
function generationApplies({ generation, scout_authored }: ReportSpendApi): boolean {
    return !scout_authored || generation.total_spend !== null
}

export function ReportSpendSection({
    reportId,
    onToggleCollapsed,
}: {
    reportId: string
    onToggleCollapsed?: (collapsed: boolean) => void
}): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = reportSpendLogic({ teamId: currentTeamId ?? 0, reportId })
    const { spend, spendLoading, failed } = useValues(logic)
    const { refreshSpend } = useActions(logic)
    const ownSpend = spend ? reportOwnSpend(spend) : null

    return (
        <DetailSection
            title="Usage"
            icon={<IconReceipt />}
            collapsible
            defaultCollapsed
            onToggleCollapsed={onToggleCollapsed}
            meta={
                spend && !failed && (ownSpend !== null || !spend.scout_authored) ? (
                    <span className="text-xs text-secondary" data-attr="report-spend-total">
                        <RecordedSpend amount={ownSpend} description="Report generation and implementation." />
                    </span>
                ) : null
            }
        >
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
                    {generationApplies(spend) && (
                        <div className="flex flex-wrap justify-between gap-2">
                            <span>Report generation</span>
                            <RecordedSpend amount={spend.generation.total_spend} />
                        </div>
                    )}
                    {spend.implementation.total_spend !== null && (
                        <div className="flex flex-wrap justify-between gap-2">
                            <span>Implementation</span>
                            <RecordedSpend amount={spend.implementation.total_spend} />
                        </div>
                    )}
                    {spend.scout_authored && (
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
