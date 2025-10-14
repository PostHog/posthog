import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconShare } from '@posthog/icons'
import { LemonBanner, LemonDivider, LemonSelect, LemonTabs } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    SelectPrimitive,
    SelectPrimitiveContent,
    SelectPrimitiveGroup,
    SelectPrimitiveItem,
    SelectPrimitiveLabel,
    SelectPrimitiveSeparator,
    SelectPrimitiveTrigger,
    SelectPrimitiveValue,
} from 'lib/ui/SelectPrimitive/SelectPrimitive'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SidePanelTab } from '~/types'

import { EventsTable, EventsTableV2, EventsV2Table } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

export function V2Layout(): JSX.Element {
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')
    const { openSidePanel } = useActions(sidePanelLogic)

    const isPostHogSDKIssue = selectedEvent?.properties.$exception_values?.some((v: string) =>
        v.includes('persistence.isDisabled is not a function')
    )

    return (
        <ErrorTrackingSetupPrompt>
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

            <div className="ErrorTrackingIssue grid grid-cols-10 gap-6">
                <div className="col-span-3 border-r flex flex-col min-h-0">
                    <div className="flex justify-between p-1">
                        <SceneBreadcrumbBackButton />
                        <div>
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
                        </div>
                    </div>
                    <LemonDivider className="my-0" />
                    <div className="p-2">
                        <ErrorTrackingIssueScenePanel showActions={false} />
                    </div>
                </div>
                <div className="col-span-7">
                    <PanelTabs />
                </div>
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

const PanelTabs = (): JSX.Element => {
    const { issue, issueLoading, initialEventLoading, initialEvent, selectedEvent, eventsQuery, eventsQueryKey } =
        useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()

    const [mode, setMode] = useState<string>('last_seen')

    return (
        <TabsPrimitive value="exceptions" className="space-y-2">
            <TabsPrimitiveList className="flex justify-between items-center border-b">
                <TabsPrimitiveTrigger value="exceptions">
                    <SelectPrimitive value={mode} onValueChange={(value) => setMode(value)}>
                        <SelectPrimitiveTrigger className="text-primary-3000 my-1">
                            {mode === 'last_seen'
                                ? 'Last seen'
                                : mode === 'all'
                                  ? 'All exceptions'
                                  : (selectedEvent?.uuid ?? 'Exception')}
                        </SelectPrimitiveTrigger>
                        <SelectPrimitiveContent matchTriggerWidth>
                            <SelectPrimitiveGroup>
                                <SelectPrimitiveItem value="last_seen">Last seen</SelectPrimitiveItem>
                                {selectedEvent?.uuid != initialEvent?.uuid && (
                                    <SelectPrimitiveItem value="current_exception" className="flex-nowrap">
                                        {selectedEvent?.uuid ?? 'Current exception'}
                                    </SelectPrimitiveItem>
                                )}
                                <SelectPrimitiveSeparator />
                                <SelectPrimitiveItem value="all">All exceptions</SelectPrimitiveItem>
                            </SelectPrimitiveGroup>
                        </SelectPrimitiveContent>
                    </SelectPrimitive>
                </TabsPrimitiveTrigger>
            </TabsPrimitiveList>
            <TabsPrimitiveContent value="exceptions">
                {mode === 'all' ? (
                    <div className="space-y-2">
                        <ErrorFilters.Root>
                            <div className="flex flex-wrap justify-between gap-2">
                                <ErrorFilters.DateRange />
                                <ErrorFilters.InternalAccounts />
                            </div>
                            <ErrorFilters.FilterGroup />
                        </ErrorFilters.Root>
                        <Metadata className="flex flex-col h-full min-h-0">
                            <div className="flex-1 min-h-0 overflow-auto">
                                <EventsTableV2
                                    query={eventsQuery}
                                    queryKey={eventsQueryKey}
                                    selectedEvent={selectedEvent}
                                    onEventSelect={(selectedEvent) => {
                                        if (selectedEvent) {
                                            selectEvent(selectedEvent)
                                            setMode('current_exception')
                                        }
                                    }}
                                />
                            </div>
                        </Metadata>
                    </div>
                ) : (
                    <ExceptionCard
                        issue={issue ?? undefined}
                        issueLoading={issueLoading}
                        event={selectedEvent ?? undefined}
                        eventLoading={initialEventLoading}
                        label={tagRenderer(selectedEvent)}
                    />
                )}
            </TabsPrimitiveContent>
        </TabsPrimitive>
    )
}
