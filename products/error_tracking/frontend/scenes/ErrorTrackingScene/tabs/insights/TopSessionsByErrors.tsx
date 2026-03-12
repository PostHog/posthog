import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface TopSession {
    sessionId: string
    distinctId: string
    errorCount: number
    issueCount: number
}

export function TopSessionsByErrors(): JSX.Element {
    const { topSessionsByErrors, topSessionsByErrorsLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (topSessionsByErrors ?? []) as TopSession[]

    return (
        <TableCard
            title="Top sessions by errors"
            description="Sessions with the most exceptions"
            loading={topSessionsByErrorsLoading}
        >
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">Session</th>
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
                                        icon={<IconPlayCircle />}
                                        to={urls.replaySingle(row.sessionId)}
                                        targetBlank
                                    >
                                        Watch session
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
