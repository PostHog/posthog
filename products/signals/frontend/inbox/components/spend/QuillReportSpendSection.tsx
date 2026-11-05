import { useActions, useValues } from 'kea'

import { IconReceipt } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemDescription, Skeleton, Text } from '@posthog/quill'

import { teamLogic } from 'scenes/teamLogic'

import { reportSpendLogic } from '../../logics/reportSpendLogic'
import { QuillDetailSection } from '../detail/QuillDetailSection'
import { QuillRecordedSpend } from './QuillRecordedSpend'

/** The quill sibling of `ReportSpendSection`, for the report page behind `today-rail-nav`. */
export function QuillReportSpendSection({ reportId }: { reportId: string }): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const logic = reportSpendLogic({ teamId: currentTeamId ?? 0, reportId })
    const { spend, spendLoading, failed } = useValues(logic)
    const { refreshSpend } = useActions(logic)

    return (
        <QuillDetailSection title="Usage" icon={<IconReceipt />}>
            {failed ? (
                <Item variant="outline" tone="destructive" size="sm">
                    <ItemContent>
                        <ItemDescription>Couldn't load usage.</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button variant="outline" onClick={() => refreshSpend()} loading={spendLoading}>
                            Retry
                        </Button>
                    </ItemActions>
                </Item>
            ) : !spend ? (
                <Skeleton className="h-8 w-full" />
            ) : (
                <div className="flex flex-col gap-2" data-attr="report-spend">
                    <Text size="xs" render={<div />} className="flex flex-wrap justify-between gap-2">
                        <span>Report generation</span>
                        <QuillRecordedSpend amount={spend.generation.total_spend} />
                    </Text>
                    {spend.implementation.total_spend !== null && (
                        <Text size="xs" render={<div />} className="flex flex-wrap justify-between gap-2">
                            <span>Implementation</span>
                            <QuillRecordedSpend amount={spend.implementation.total_spend} />
                        </Text>
                    )}
                    {spend.shared_scout_runs.total_spend !== null && (
                        <div className="flex flex-col gap-1">
                            <Text size="xs" render={<div />} className="flex flex-wrap justify-between gap-2">
                                <span>Authoring scout runs</span>
                                <QuillRecordedSpend amount={spend.shared_scout_runs.total_spend} />
                            </Text>
                            <Text size="xs" variant="muted" className="m-0">
                                Shared across all output of these runs.
                            </Text>
                        </div>
                    )}
                </div>
            )}
        </QuillDetailSection>
    )
}
