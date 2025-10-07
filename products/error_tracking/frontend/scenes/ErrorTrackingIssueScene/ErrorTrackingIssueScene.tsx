import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { Header } from './Header'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

export const scene: SceneExport<ErrorTrackingIssueSceneLogicProps> = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({ params: { id }, searchParams: { fingerprint, timestamp } }) => ({ id, fingerprint, timestamp }),
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueLoading, selectedEvent, initialEventLoading, eventsQuery, eventsQueryKey } =
        useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()

    const isPostHogSDKIssue = selectedEvent?.properties.$exception_values?.some((v: string) =>
        v.includes('persistence.isDisabled is not a function')
    )

    return (
        <ErrorTrackingSetupPrompt>
            <Header />

            {isPostHogSDKIssue && (
                <LemonBanner
                    type="error"
                    action={{ to: 'https://status.posthog.com/incidents/l70cgmt7475m', children: 'Read more' }}
                    className="mb-4"
                >
                    This issue was captured because of a bug in the PostHog SDK. We've fixed the issue, and you won't be
                    charged for any of these exception events. We recommend setting this issue's status to "Suppressed".
                </LemonBanner>
            )}

            <div className="ErrorTrackingIssue grid grid-cols-4 gap-4">
                <div className="space-y-2 col-span-3">
                    <ExceptionCard
                        issue={issue ?? undefined}
                        issueLoading={issueLoading}
                        event={selectedEvent ?? undefined}
                        eventLoading={initialEventLoading}
                        label={tagRenderer(selectedEvent)}
                    />
                    <ErrorFilters.Root>
                        <div className="flex gap-2 justify-between">
                            <ErrorFilters.DateRange />
                            <ErrorFilters.InternalAccounts />
                        </div>
                        <ErrorFilters.FilterGroup />
                    </ErrorFilters.Root>
                    <Metadata>
                        <EventsTable
                            query={eventsQuery}
                            queryKey={eventsQueryKey}
                            selectedEvent={selectedEvent}
                            onEventSelect={(selectedEvent) => (selectedEvent ? selectEvent(selectedEvent) : null)}
                        />
                    </Metadata>
                </div>
                <ErrorTrackingIssueScenePanel />
            </div>
        </ErrorTrackingSetupPrompt>
    )
}
