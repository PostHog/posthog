import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { DescriptiveSelect } from './DescriptiveSelect'
import { errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'
import { SessionEndingIssue } from './errorTrackingInsightsLogic'
import {
    SESSION_ENDING_EVENT_THRESHOLDS,
    SESSION_ENDING_STRATEGY_OPTIONS,
    SESSION_ENDING_TIME_THRESHOLDS,
} from './queries'
import { TableCard } from './TableCard'

export function SessionEndingIssues(): JSX.Element {
    const {
        sessionEndingIssues,
        sessionEndingIssuesLoading,
        sessionEndingStrategy,
        sessionEndingTimeThreshold,
        sessionEndingEventThreshold,
    } = useValues(errorTrackingInsightsLogic)
    const { setSessionEndingStrategy, setSessionEndingTimeThreshold, setSessionEndingEventThreshold } =
        useActions(errorTrackingInsightsLogic)

    const rows = (sessionEndingIssues ?? []) as SessionEndingIssue[]

    const config = (
        <>
            <DescriptiveSelect
                value={sessionEndingStrategy}
                onChange={setSessionEndingStrategy}
                options={SESSION_ENDING_STRATEGY_OPTIONS}
            />
            {sessionEndingStrategy === 'time' && (
                <LemonSelect
                    size="xsmall"
                    value={sessionEndingTimeThreshold}
                    onChange={setSessionEndingTimeThreshold}
                    options={SESSION_ENDING_TIME_THRESHOLDS.map((s) => ({ value: s, label: `${s}s` }))}
                />
            )}
            {sessionEndingStrategy === 'event' && (
                <LemonSelect
                    size="xsmall"
                    value={sessionEndingEventThreshold}
                    onChange={setSessionEndingEventThreshold}
                    options={SESSION_ENDING_EVENT_THRESHOLDS.map((n) => ({
                        value: n,
                        label: `${n} event${n === 1 ? '' : 's'}`,
                    }))}
                />
            )}
        </>
    )

    return (
        <TableCard
            title="Session-ending issues"
            description="Issues that ended the most sessions"
            loading={sessionEndingIssuesLoading}
            config={config}
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
                                <td className="py-1.5 px-2 text-sm max-w-60">
                                    <p className="m-0 truncate font-medium">{row.issueName || 'Unknown error'}</p>
                                    {row.issueDescription && (
                                        <p className="text-xs text-secondary m-0 truncate">{row.issueDescription}</p>
                                    )}
                                </td>
                                <td className="py-1.5 px-2 text-sm text-right font-medium">{row.endedSessions}</td>
                                <td className="py-1.5 px-2 text-right w-px whitespace-nowrap">
                                    <div className="flex gap-1 justify-end">
                                        {row.exampleRecordingSessionId && (
                                            <LemonButton
                                                type="secondary"
                                                size="xsmall"
                                                to={urls.replaySingle(row.exampleRecordingSessionId)}
                                                targetBlank
                                            >
                                                View recording
                                            </LemonButton>
                                        )}
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            to={urls.errorTrackingIssue(row.issueId)}
                                            targetBlank
                                        >
                                            View issue
                                        </LemonButton>
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
