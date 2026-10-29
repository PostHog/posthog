import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { captureInboxPanelViewed } from '../../inboxAnalytics'
import { inboxActivationLogic } from '../../logics/inboxActivationLogic'
import { ScoutSuggestionCard } from '../config/scouts/ScoutSuggestionCard'
import { ScoutSuggestionCreateHost } from '../config/scouts/ScoutSuggestionCreateHost'

interface InboxActivationPanelProps {
    hasReports?: boolean
}

export function InboxActivationPanel({ hasReports = false }: InboxActivationPanelProps): JSX.Element {
    const { savedState, sourceNames, generalScout, suggestions, recommendationsReady, pollingExpired, currentTeamId } =
        useValues(inboxActivationLogic)
    // The first report is the main content while that state exists, as a progress card and then as a
    // report row under this panel, so the panel starts folded to its header.
    const [expanded, setExpanded] = useState(!savedState?.first_report)
    const { reportRecommendationsShown } = useActions(inboxActivationLogic)
    useEffect(() => {
        captureInboxPanelViewed({ panel: 'onboarding' })
    }, [currentTeamId])
    useEffect(() => {
        if (suggestions.length > 0) {
            reportRecommendationsShown()
        }
    }, [suggestions, reportRecommendationsShown])
    const jobs = savedState?.jobs
    return (
        <LemonCard hoverEffect={false} className="@container flex flex-col gap-3" data-attr="inbox-activation-panel">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="m-0 flex items-center gap-2 text-base">
                    <IconCheckCircle className="text-success" />
                    Your setup is complete
                </h3>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => setExpanded(!expanded)}
                    aria-expanded={expanded}
                    data-attr="inbox-activation-explore"
                >
                    {expanded ? 'Show less' : 'Explore what’s enabled'}
                </LemonButton>
            </div>
            {expanded && (
                <>
                    <div className="flex flex-wrap gap-2">
                        {sourceNames.map((name) => (
                            <LemonTag key={name}>{name}</LemonTag>
                        ))}
                        {generalScout?.enabled && <LemonTag type="success">General scout</LemonTag>}
                    </div>
                    <p className="m-0 text-sm text-secondary">
                        Sources alert agents to issues as they appear, so they can investigate right away. Scouts
                        explore your code and all your data to uncover issues and connect patterns. Reports arrive with
                        evidence and next steps.
                    </p>
                    {!hasReports && !savedState?.first_report && generalScout?.enabled && (
                        <p className="m-0 text-sm" aria-live="polite">
                            {jobs?.scout === 'pending'
                                ? 'Preparing your first general scout run.'
                                : jobs?.scout === 'started'
                                  ? 'Your first general scout run has been requested. You can leave this page while it works.'
                                  : jobs?.scout === 'failed'
                                    ? 'Your first run could not be started. Open the general scout to try running it.'
                                    : jobs?.scout === 'skipped'
                                      ? 'Your first run could not start under the current project settings or limits. Review your scout settings.'
                                      : 'Your general scout will run on its schedule.'}
                        </p>
                    )}
                </>
            )}
            {expanded && (
                <div className="flex flex-wrap gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.inbox('sources')}
                        data-attr="inbox-activation-sources"
                    >
                        Manage sources
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.inbox('scouts')}
                        data-attr="inbox-activation-scouts"
                    >
                        Add or manage scouts
                    </LemonButton>
                    <LemonButton
                        size="small"
                        to="https://posthog.com/docs/self-driving"
                        targetBlank
                        data-attr="inbox-activation-learn"
                    >
                        How it works
                    </LemonButton>
                </div>
            )}
            {suggestions.length > 0 ? (
                <section className="flex flex-col gap-2 border-t border-primary pt-3">
                    <h4 className="m-0">Recommended for your product</h4>
                    <p className="m-0 text-sm text-secondary">Choose what you’d like to investigate next.</p>
                    <div className="divide-y divide-primary">
                        {suggestions.map((item) => (
                            <ScoutSuggestionCard key={item.id} item={item} surface="onboarding" />
                        ))}
                    </div>
                    <ScoutSuggestionCreateHost surface="onboarding" />
                </section>
            ) : !pollingExpired &&
              !recommendationsReady &&
              (jobs?.recommendations === 'pending' || jobs?.recommendations === 'started') ? (
                <div className="flex items-center gap-2 text-sm text-secondary">
                    <Spinner />
                    <span>Preparing scout recommendations. They’ll appear here when ready.</span>
                </div>
            ) : jobs?.recommendations === 'failed' || pollingExpired ? (
                <p className="m-0 text-sm text-secondary">
                    <span>
                        {pollingExpired
                            ? 'Recommendations are not available yet. '
                            : 'Recommendations could not be prepared. '}
                    </span>
                    <Link to={urls.inbox('scouts')}>Explore scouts</Link> to choose what to investigate.
                </p>
            ) : null}
            <p className="m-0 border-t border-primary pt-3 text-xs text-secondary">
                Create or configure scouts with PostHog AI, the PostHog Slack Bot, or an agent connected through{' '}
                <Link to="https://posthog.com/docs/model-context-protocol" target="_blank">
                    MCP
                </Link>
                .
            </p>
        </LemonCard>
    )
}
