import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonSegmentedButton } from '@posthog/lemon-ui'

import { AgentAnalyticsIssues } from './AgentAnalyticsIssues'
import { AgentAnalyticsJourneys } from './AgentAnalyticsJourneys'
import { AgentView, agentAnalyticsLogic } from './agentAnalyticsLogic'
import { AgentAnalyticsOverview } from './AgentAnalyticsOverview'
import { AgentAnalyticsReadiness } from './AgentAnalyticsReadiness'

const VIEW_OPTIONS: { value: AgentView; label: string }[] = [
    { value: 'overview', label: 'Overview' },
    { value: 'journeys', label: 'Journeys' },
    { value: 'issues', label: 'Issues' },
    { value: 'readiness', label: 'Readiness' },
]

export const AgentAnalytics = (): JSX.Element => {
    useMountedLogic(agentAnalyticsLogic)
    const { view } = useValues(agentAnalyticsLogic)
    const { setView } = useActions(agentAnalyticsLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonBanner
                type="info"
                dismissKey="web-analytics-agent-analytics-feedback-banner"
                action={{ children: 'Send feedback', id: 'web-analytics-agent-analytics-feedback-button' }}
            >
                Track what AI agents read, where requests fail, and which fixes have the most demand. Connect
                server-side HTTP logs for complete coverage.
            </LemonBanner>
            <LemonSegmentedButton value={view} onChange={setView} options={VIEW_OPTIONS} size="small" />
            {view === 'overview' ? (
                <AgentAnalyticsOverview />
            ) : view === 'journeys' ? (
                <AgentAnalyticsJourneys />
            ) : view === 'issues' ? (
                <AgentAnalyticsIssues />
            ) : (
                <AgentAnalyticsReadiness />
            )}
        </div>
    )
}
