import './ErrorTrackingIssueScene.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useRef, useState } from 'react'

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
        <div className="flex flex-1 flex-col gap-y-1 pl-4 overflow-y-auto">
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

const CLOSE_THRESHOLD = 300

const LeftHandColumn = (): JSX.Element => {
    const ref = useRef<HTMLDivElement>(null)
    const [isClosed, setIsClosed] = useState<boolean>(false)
    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'error-tracking-issue',
        persistent: true,
        closeThreshold: CLOSE_THRESHOLD,
        onToggleClosed: (closed) => setIsClosed(closed),
        onDoubleClick: () => setIsClosed(!isClosed),
        placement: 'right',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const hasDiscussions = useFeatureFlag('DISCUSSIONS')

    const style = isClosed ? {} : { width: desiredSize ?? '30%', minWidth: CLOSE_THRESHOLD + 80 }

    const comment = (
        <ButtonPrimitive
            onClick={() => {
                if (!hasDiscussions) {
                    posthog.updateEarlyAccessFeatureEnrollment('discussions', true)
                }
                openSidePanel(SidePanelTab.Discussion)
            }}
            tooltip="Comment"
            iconOnly={isClosed}
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
            iconOnly={isClosed}
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
            {isClosed ? (
                <div className="flex flex-col pr-0.5">
                    <SceneBreadcrumbBackButton iconOnly />
                    {comment}
                    {copyLink}
                    <LemonDivider />
                    <ButtonPrimitive onClick={() => {}} iconOnly tooltip="Overview">
                        <IconWarning />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => {}} iconOnly tooltip="Exceptions">
                        <IconList />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => {}} iconOnly tooltip="Breakdowns">
                        <IconFilter />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => {}} iconOnly tooltip="AI Autofix">
                        <IconRobot />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => {}} iconOnly tooltip="Similar issues">
                        <IconSearch />
                    </ButtonPrimitive>
                </div>
            ) : (
                <>
                    <div className="flex justify-between items-center pr-1">
                        <SceneBreadcrumbBackButton />
                        <div>
                            {comment}
                            {copyLink}
                        </div>
                    </div>

                    <LemonDivider className="mt-1" />

                    <TabsPrimitive defaultValue="overview" className="flex flex-col gap-y-2">
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
                                <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="similar_issues">
                                    <IconSearch className="mr-1" />
                                    <span className="text-nowrap">Similar issues</span>
                                </TabsPrimitiveTrigger>
                            </TabsPrimitiveList>
                        </ScrollableShadows>
                        <TabsPrimitiveContent value="overview" className="pr-2">
                            <ErrorTrackingIssueScenePanel showActions={false} />
                        </TabsPrimitiveContent>
                        <TabsPrimitiveContent value="exceptions">
                            <ExceptionsTab />
                        </TabsPrimitiveContent>
                        <TabsPrimitiveContent value="breakdowns">
                            <BreakdownsSearchBar />
                            <BreakdownsChart />
                        </TabsPrimitiveContent>
                        <TabsPrimitiveContent value="autofix">AI autofix</TabsPrimitiveContent>
                        <TabsPrimitiveContent value="similar_issues">Similar issues</TabsPrimitiveContent>
                    </TabsPrimitive>
                </>
            )}

            <Resizer {...resizerLogicProps} />
        </div>
    )
}

const ExceptionsTab = (): JSX.Element => {
    const { eventsQuery, eventsQueryKey } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent, setExceptionsCategory } = useActions(errorTrackingIssueSceneLogic)

    return (
        <div className="flex flex-col gap-y-2 pr-2">
            <ErrorFilters.Root>
                <div className="flex gap-2 justify-between">
                    <ErrorFilters.DateRange />
                    <ErrorFilters.InternalAccounts />
                </div>
                <ErrorFilters.FilterGroup />
            </ErrorFilters.Root>
            <Metadata className="">
                <EventsTable
                    query={eventsQuery}
                    queryKey={eventsQueryKey}
                    selectedEvent={null}
                    onEventSelect={(selectedEvent) => {
                        if (selectedEvent) {
                            selectEvent(selectedEvent)
                            setExceptionsCategory('exception')
                        }
                    }}
                />
            </Metadata>
        </div>
    )
}
