import { useEffect, useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { DashboardImportAgentActivityApi } from 'products/metrics/frontend/generated/api.schemas'

// The agent's tool calls take seconds, so a few minutes with no log entry is worth telling the user about.
const STALLED_AFTER_SECONDS = 180

function describeAction({ kind, subject, panel_count }: DashboardImportAgentActivityApi): JSX.Element | string {
    switch (kind) {
        case 'searching_metrics':
            return subject ? (
                <>
                    <span>Searching metrics for </span>
                    <span translate="no">“{subject}”</span>
                </>
            ) : (
                'Searching metrics'
            )
        case 'reading_labels':
            return subject ? (
                <>
                    <span>Reading labels of </span>
                    <code translate="no">{subject}</code>
                </>
            ) : (
                'Reading metric labels'
            )
        case 'reading_label_values':
            return subject ? (
                <>
                    <span>Reading values of </span>
                    <code translate="no">{subject}</code>
                </>
            ) : (
                'Reading label values'
            )
        case 'running_query':
            return 'Running a test query'
        case 'checking_panels':
            return panel_count ? `Checking ${panel_count} ${panel_count === 1 ? 'panel' : 'panels'}` : 'Checking panels'
        case 'exploring_logs':
            return 'Looking up logs'
        case 'exploring_traces':
            return 'Looking up traces'
        case 'reading_dashboard':
            return 'Reading the dashboard'
        case 'thinking':
            return 'Thinking'
        default:
            return 'Working'
    }
}

export function DashboardImportAgentActivity({ activity }: { activity: DashboardImportAgentActivityApi }): JSX.Element {
    // The server sends elapsed seconds, not timestamps, so a wrong clock on the user's computer cannot skew the timer.
    const [secondsSincePoll, setSecondsSincePoll] = useState(0)
    const { isVisible: isPageVisible } = usePageVisibility()

    useEffect(() => {
        const receivedAt = Date.now()
        setSecondsSincePoll(0)
        if (!isPageVisible) {
            return
        }
        const interval = setInterval(() => setSecondsSincePoll(Math.floor((Date.now() - receivedAt) / 1000)), 1000)
        return () => clearInterval(interval)
    }, [activity, isPageVisible])

    const idleSeconds = activity.idle_seconds + secondsSincePoll

    if (idleSeconds >= STALLED_AFTER_SECONDS) {
        return (
            <div className="flex items-center gap-2 text-sm min-w-0" data-attr="metrics-dashboard-import-agent-stalled">
                <IconWarning className="text-warning-dark text-base shrink-0" />
                <span className="flex-1 min-w-0 truncate text-warning-dark">
                    <span>No new agent actions for </span>
                    <span translate="no">{humanFriendlyDuration(idleSeconds)}</span>
                </span>
                {/* Any kind but thinking is a tool call that has not returned, so name the step the agent waits on. */}
                {activity.kind !== 'thinking' ? (
                    <span className="shrink-0 max-w-1/2 truncate text-xs text-muted">
                        <span>Waiting on: </span>
                        <span>{describeAction(activity)}</span>
                    </span>
                ) : null}
            </div>
        )
    }

    return (
        <div className="flex items-center gap-2 text-sm text-secondary min-w-0">
            <Spinner className="text-base shrink-0" />
            <span className="flex-1 min-w-0 truncate text-default">{describeAction(activity)}</span>
            <span className="shrink-0 text-xs text-muted" translate="no">
                {humanFriendlyDuration(activity.seconds + secondsSincePoll)}
            </span>
        </div>
    )
}
