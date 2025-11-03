import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef } from 'react'

import { IconFilter, IconList, IconSearch, IconShare, IconWarning } from '@posthog/icons'
import { LemonBanner, LemonDivider } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconComment, IconRobot } from 'lib/lemon-ui/icons'
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
import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SidePanelTab } from '~/types'

import { BreakdownsChart } from '../../components/Breakdowns/BreakdownsChart'
import { BreakdownsSearchBar } from '../../components/Breakdowns/BreakdownsSearchBar'
import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { Metadata } from '../../components/IssueMetadata'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { SimilarIssuesList } from './ScenePanel/SimilarIssuesList'
import { errorTrackingIssueSceneConfigurationLogic } from './errorTrackingIssueSceneConfigurationLogic'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

export function V2Layout(): JSX.Element {
    const { selectedEvent } = useValues(errorTrackingIssueSceneLogic)

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

            <div className="ErrorTrackingIssue flex h-full min-h-0">
                <LeftHandColumn />
                <RightHandColumn />
            </div>
        </ErrorTrackingSetupPrompt>
    )
}

const RightHandColumn = (): JSX.Element => {
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()

    return (
        <div className="flex flex-1 flex-col gap-y-1 pl-4 overflow-y-auto min-w-[375px]">
            <ExceptionCard
                issue={issue ?? undefined}
                issueLoading={issueLoading}
                event={selectedEvent ?? undefined}
                eventLoading={initialEventLoading}
                label={tagRenderer(selectedEvent)}
            />
        </div>
    )
}

const CLOSE_THRESHOLD = 370

const LeftHandColumn = (): JSX.Element => {
    const { category, isSidebarOpen } = useValues(errorTrackingIssueSceneConfigurationLogic)
    const { setCategory, setIsSidebarOpen } = useActions(errorTrackingIssueSceneConfigurationLogic)

    const ref = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'error-tracking-issue',
        persistent: true,
        closeThreshold: CLOSE_THRESHOLD,
        onToggleClosed: (open) => setIsSidebarOpen(open),
        onDoubleClick: () => setIsSidebarOpen(!isSidebarOpen),
        placement: 'right',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')

    const style = isSidebarOpen ? { width: desiredSize ?? '30%', minWidth: CLOSE_THRESHOLD + 80 } : {}

    const comment = (
        <ButtonPrimitive
            onClick={() => {
                if (!hasDiscussions) {
                    posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                }
                openSidePanel(SidePanelTab.Discussion)
            }}
            tooltip="Comment"
            iconOnly={!isSidebarOpen}
        >
            <IconComment />
        </ButtonPrimitive>
    )

    const copyLink = (
        <ButtonPrimitive
            onClick={() => {
                if (issue) {
                    void copyToClipboard(window.location.origin + urls.errorTrackingIssue(issue.id), 'issue link')
                }
            }}
            iconOnly={!isSidebarOpen}
            tooltip="Share"
        >
            <IconShare />
        </ButtonPrimitive>
    )

    return (
        <div
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={style}
            className="flex flex-col relative"
        >
            {isSidebarOpen ? (
                <>
                    <div className="flex justify-between items-center pr-1">
                        <SceneBreadcrumbBackButton />
                        <div>
                            {comment}
                            {copyLink}
                        </div>
                    </div>

                    <LemonDivider className="mt-1" />

                    <TabsPrimitive
                        value={category}
                        onValueChange={(value) => setCategory(value)}
                        className="flex flex-col min-h-0"
                    >
                        <div>
                            <ScrollableShadows direction="horizontal" className="border-b" hideScrollbars>
                                <TabsPrimitiveList className="flex justify-between space-x-2">
                                    <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="overview">
                                        <IconWarning className="mr-1" />
                                        <span className="text-nowrap">Overview</span>
                                    </TabsPrimitiveTrigger>
                                    <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="exceptions">
                                        <IconList className="mr-1" />
                                        <span className="text-nowrap">Exceptions</span>
                                    </TabsPrimitiveTrigger>
                                    <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="breakdowns">
                                        <IconFilter className="mr-1" />
                                        <span className="text-nowrap">Breakdowns</span>
                                    </TabsPrimitiveTrigger>
                                    <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="autofix">
                                        <IconRobot className="mr-1" />
                                        <span className="text-nowrap">Autofix</span>
                                    </TabsPrimitiveTrigger>
                                    <TabsPrimitiveTrigger
                                        className="flex items-center px-2 py-1.5"
                                        value="similar_issues"
                                    >
                                        <IconSearch className="mr-1" />
                                        <span className="text-nowrap">Similar issues</span>
                                    </TabsPrimitiveTrigger>
                                </TabsPrimitiveList>
                            </ScrollableShadows>
                        </div>
                        <TabsPrimitiveContent value="overview" className="flex flex-col overflow-y-auto pt-2 pr-2">
                            <ErrorTrackingIssueScenePanel showActions={false} showSimilarIssues={false} />
                        </TabsPrimitiveContent>
                        <TabsPrimitiveContent value="exceptions" className="h-full min-h-0">
                            <ExceptionsTab />
                        </TabsPrimitiveContent>
                        <TabsPrimitiveContent value="breakdowns">
                            <BreakdownsSearchBar />
                            <BreakdownsChart />
                        </TabsPrimitiveContent>
                        <TabsPrimitiveContent value="autofix">AI autofix</TabsPrimitiveContent>
                        <TabsPrimitiveContent value="similar_issues">
                            <SimilarIssuesList />
                        </TabsPrimitiveContent>
                    </TabsPrimitive>
                </>
            ) : (
                <div className="flex flex-col pr-0.5">
                    <SceneBreadcrumbBackButton iconOnly />
                    {comment}
                    {copyLink}
                    <LemonDivider />
                    <ButtonPrimitive onClick={() => setCategory('overview')} iconOnly tooltip="Overview">
                        <IconWarning />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => setCategory('exceptions')} iconOnly tooltip="Exceptions">
                        <IconList />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => setCategory('breakdowns')} iconOnly tooltip="Breakdowns">
                        <IconFilter />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => setCategory('autofix')} iconOnly tooltip="AI Autofix">
                        <IconRobot />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => setCategory('similar_issues')} iconOnly tooltip="Similar issues">
                        <IconSearch />
                    </ButtonPrimitive>
                </div>
            )}

            <Resizer {...resizerLogicProps} />
        </div>
    )
}

const ExceptionsTab = (): JSX.Element => {
    const { eventsQuery, eventsQueryKey } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)

    return (
        <div className="flex flex-col h-full gap-y-2">
            <ErrorFilters.Root className="pt-2 pr-2">
                <div className="flex gap-2 justify-between flex-wrap">
                    <ErrorFilters.DateRange />
                    <ErrorFilters.InternalAccounts />
                </div>
                <ErrorFilters.FilterGroup />
            </ErrorFilters.Root>
            <Metadata className="flex flex-col overflow-y-auto rounded-r-none border-r-0">
                <EventsTable
                    query={eventsQuery}
                    queryKey={eventsQueryKey}
                    selectedEvent={null}
                    onEventSelect={(selectedEvent) => {
                        if (selectedEvent) {
                            selectEvent(selectedEvent)
                        }
                    }}
                />
            </Metadata>
        </div>
    )
}
