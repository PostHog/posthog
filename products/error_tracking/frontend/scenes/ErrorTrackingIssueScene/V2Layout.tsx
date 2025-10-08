import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconShare } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { EventsTable, EventsV2Table } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

export function V2Layout(): JSX.Element {
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const { openSidePanel } = useActions(sidePanelLogic)

    const isPostHogSDKIssue = selectedEvent?.properties.$exception_values?.some((v: string) =>
        v.includes('persistence.isDisabled is not a function')
    )

    return (
        <ErrorTrackingSetupPrompt>
            <div className="flex justify-between mb-2 -ml-[var(--button-padding-x-lg)]">
                <SceneTitleSection
                    name={null}
                    description={null}
                    resourceType={{ type: 'error_tracking' }}
                    actions={
                        <>
                            <ButtonPrimitive
                                onClick={() => {
                                    if (!hasDiscussions) {
                                        posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                                    }
                                    openSidePanel(SidePanelTab.Discussion)
                                }}
                                tooltip="Comment"
                            >
                                <IconComment />
                            </ButtonPrimitive>

                            <ButtonPrimitive
                                onClick={() => {
                                    if (issue) {
                                        void copyToClipboard(
                                            window.location.origin + urls.errorTrackingIssue(issue.id),
                                            'issue link'
                                        )
                                    }
                                }}
                                tooltip="Share"
                            >
                                <IconShare />
                            </ButtonPrimitive>
                        </>
                    }
                />
            </div>

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

            <div className="ErrorTrackingIssue grid grid-cols-10 gap-4 h-[calc(100vh-182px)]">
                <div className="col-span-4 border-r pr-4 flex flex-col min-h-0">
                    <PanelTabs />
                </div>
                <div className="col-span-6">
                    <ExceptionCard
                        issue={issue ?? undefined}
                        issueLoading={issueLoading}
                        event={selectedEvent ?? undefined}
                        eventLoading={initialEventLoading}
                        label={tagRenderer(selectedEvent)}
                    />
                </div>
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

const PanelTabs = (): JSX.Element => {
    const { selectedEvent, eventsQuery, eventsQueryKey } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)

    return (
        <TabsPrimitive defaultValue="issue" className="h-full flex flex-col">
            <div className="flex mb-2 gap-x-2">
                <TabsPrimitiveList>
                    <TabsPrimitiveTrigger className="px-2" value="issue">
                        Issue
                    </TabsPrimitiveTrigger>
                    <TabsPrimitiveTrigger className="px-2" value="exceptions">
                        Exceptions
                    </TabsPrimitiveTrigger>
                </TabsPrimitiveList>
            </div>
            <TabsPrimitiveContent value="issue">
                <ErrorTrackingIssueScenePanel showActions={false} />
            </TabsPrimitiveContent>
            <TabsPrimitiveContent value="exceptions" className="space-y-2 flex-1 min-h-0 flex flex-col">
                <ErrorFilters.Root>
                    <div className="flex flex-wrap justify-between gap-2">
                        <ErrorFilters.DateRange />
                        <ErrorFilters.InternalAccounts />
                    </div>
                    <ErrorFilters.FilterGroup />
                </ErrorFilters.Root>
                <Metadata>
                    <div className="flex-1 min-h-0 overflow-auto">
                        <EventsV2Table
                            query={eventsQuery}
                            queryKey={eventsQueryKey}
                            selectedEvent={selectedEvent}
                            onEventSelect={(selectedEvent) => (selectedEvent ? selectEvent(selectedEvent) : null)}
                        />
                    </div>
                </Metadata>
            </TabsPrimitiveContent>
        </TabsPrimitive>
    )
}
