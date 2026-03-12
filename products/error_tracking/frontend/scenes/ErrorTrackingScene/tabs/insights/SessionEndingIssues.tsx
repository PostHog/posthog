import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface SessionEndingIssue {
    issueId: string
    issueName: string
    endedSessions: number
}

export function SessionEndingIssues(): JSX.Element {
    const { sessionEndingIssues, sessionEndingIssuesLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (sessionEndingIssues ?? []) as SessionEndingIssue[]

    return (
        <TableCard
            title="Session-ending issues"
            description="Issues that ended the most sessions (no activity within 5s)"
            loading={sessionEndingIssuesLoading}
        >
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">Issue</th>
                            <th className="text-right font-medium py-1.5 px-2 whitespace-nowrap">Sessions ended</th>
                            <th className="text-right font-medium py-1.5 px-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, i) => (
                            <tr key={i} className="border-b last:border-b-0 hover:bg-surface-secondary">
                                <td className="py-1.5 px-2 text-sm max-w-60 truncate">
                                    <LemonButton
                                        type="tertiary"
                                        size="xsmall"
                                        to={urls.errorTrackingIssue(row.issueId)}
                                        className="max-w-full"
                                        truncate
                                    >
                                        {row.issueName || 'Unknown error'}
                                    </LemonButton>
                                </td>
                                <td className="py-1.5 px-2 text-sm text-right font-medium">{row.endedSessions}</td>
                                <td className="py-1.5 px-2 text-right">
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        to={urls.errorTrackingIssue(row.issueId)}
                                        targetBlank
                                    >
                                        View issue
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
