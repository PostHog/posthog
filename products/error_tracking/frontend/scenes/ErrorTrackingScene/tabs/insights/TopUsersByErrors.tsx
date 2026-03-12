import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface TopUser {
    distinctId: string
    errorCount: number
    issueCount: number
}

export function TopUsersByErrors(): JSX.Element {
    const { topUsersByErrors, topUsersByErrorsLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (topUsersByErrors ?? []) as TopUser[]

    return (
        <TableCard
            title="Top users by errors"
            description="Users experiencing the most exceptions"
            loading={topUsersByErrorsLoading}
        >
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">User</th>
                            <th className="text-right font-medium py-1.5 px-2">Errors</th>
                            <th className="text-right font-medium py-1.5 px-2">Issues</th>
                            <th className="text-right font-medium py-1.5 px-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, i) => (
                            <tr key={i} className="border-b last:border-b-0 hover:bg-surface-secondary">
                                <td className="py-1.5 px-2 text-sm max-w-48">
                                    <PersonDisplay person={{ distinct_id: row.distinctId }} withIcon noPopover noLink />
                                </td>
                                <td className="py-1.5 px-2 text-sm text-right font-medium">{row.errorCount}</td>
                                <td className="py-1.5 px-2 text-sm text-right text-secondary">{row.issueCount}</td>
                                <td className="py-1.5 px-2 text-right">
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        to={urls.personByDistinctId(row.distinctId)}
                                        targetBlank
                                    >
                                        View person
                                    </LemonButton>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </TableCard>
    )
}
