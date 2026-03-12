import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { IconPlayCircle } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { TableCard } from './TableCard'

interface SessionEndingError {
    issueId: string
    issueName: string
    sessionId: string
    exceptionTimestamp: string
    secondsUntilEnd: number
}

export function SessionEndingErrors(): JSX.Element {
    const { sessionEndingErrors, sessionEndingErrorsLoading } = useValues(errorTrackingInsightsLogic)

    const rows = (sessionEndingErrors ?? []) as SessionEndingError[]

    return (
        <TableCard
            title="Session-ending errors"
            description="Sessions that ended within 5s of an exception"
            loading={sessionEndingErrorsLoading}
        >
            {rows.length === 0 ? (
                <div className="flex items-center justify-center h-full text-secondary text-sm">No data</div>
            ) : (
                <table className="w-full">
                    <thead>
                        <tr className="text-xs text-secondary border-b">
                            <th className="text-left font-medium py-1.5 px-2">Issue</th>
                            <th className="text-right font-medium py-1.5 px-2 whitespace-nowrap">Time to end</th>
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
                                <td className="py-1.5 px-2 text-xs text-secondary text-right whitespace-nowrap">
                                    {row.secondsUntilEnd.toFixed(1)}s
                                </td>
                                <td className="py-1.5 px-2 text-right">
                                    <div className="flex items-center justify-end gap-1">
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            to={urls.errorTrackingIssue(row.issueId)}
                                            targetBlank
                                        >
                                            View issue
                                        </LemonButton>
                                        {row.sessionId ? (
                                            <LemonButton
                                                type="secondary"
                                                size="xsmall"
                                                icon={<IconPlayCircle />}
                                                to={urls.replaySingle(row.sessionId)}
                                                targetBlank
                                            >
                                                Watch
                                            </LemonButton>
                                        ) : null}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </TableCard>
    )
}
