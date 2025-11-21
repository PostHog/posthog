import '../ErrorTrackingIssueScene/ErrorTrackingIssueScene.scss'

import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'
import { useRef } from 'react'

import { IconComment, IconFilter, IconList, IconSearch, IconShare, IconWarning } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconRobot } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { SceneBreadcrumbBackButton } from '~/layout/scenes/components/SceneBreadcrumbs'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SidePanelTab } from '~/types'

import { PostHogSDKIssueBanner } from '../../components/Banners/PostHogSDKIssueBanner'
import { BreakdownsChart } from '../../components/Breakdowns/BreakdownsChart'
import { BreakdownsSearchBar } from '../../components/Breakdowns/BreakdownsSearchBar'
import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { ErrorFilters } from '../../components/IssueFilters'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { Metadata } from '../../components/IssueMetadata'
import { IssueTasks } from '../../components/IssueTasks'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { IssueAssigneeSelect } from './ScenePanel/IssueAssigneeSelect'
import { IssueStatusSelect } from './ScenePanel/IssueStatusSelect'
import { SimilarIssuesList } from './ScenePanel/SimilarIssuesList'
import {
    ErrorTrackingIssueSceneCategory,
    errorTrackingIssueSceneConfigurationLogic,
} from './errorTrackingIssueSceneConfigurationLogic'
import {
    ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY,
    ErrorTrackingIssueSceneLogicProps,
    errorTrackingIssueSceneLogic,
} from './errorTrackingIssueSceneLogic'

export const scene: SceneExport<ErrorTrackingIssueSceneLogicProps> = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({ params: { id }, searchParams: { fingerprint, timestamp } }) => ({ id, fingerprint, timestamp }),
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueId } = useValues(errorTrackingIssueSceneLogic)
    const { updateAssignee, updateStatus, updateName } = useActions(errorTrackingIssueSceneLogic)

    useEffect(() => {
        posthog.capture('error_tracking_issue_viewed', { issue_id: issueId })
    }, [issueId])

    return (
        <ErrorTrackingSetupPrompt>
            <BindLogic logic={issueFiltersLogic} props={{ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }}>
                {issue && (
                    <div className="px-4">
                        <SceneTitleSection
                            canEdit
                            name={issue.name}
                            onNameChange={updateName}
                            description={null}
                            resourceType={{ type: 'error_tracking' }}
                            actions={
                                <div className="flex items-center gap-2">
                                    <IssueAssigneeSelect
                                        assignee={issue.assignee}
                                        onChange={updateAssignee}
                                        disabled={issue.status != 'active'}
                                    />
                                    <IssueStatusSelect status={issue.status} onChange={updateStatus} />
                                </div>
                            }
                        />

                        <ErrorTrackingIssueScenePanel issue={issue} />
                    </div>
                )}

                <ErrorTrackingSetupPrompt>
                    <div className="ErrorTrackingIssue flex h-full min-h-0">
                        <LeftHandColumn />
                        <RightHandColumn />
                    </div>
                </ErrorTrackingSetupPrompt>
            </BindLogic>
        </ErrorTrackingSetupPrompt>
    )
}

const RightHandColumn = (): JSX.Element => {
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()

    return (
        <div className="flex flex-1 gap-y-1 pl-4 overflow-y-auto min-w-[375px]">
            <PostHogSDKIssueBanner event={selectedEvent} />

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

const CLOSE_THRESHOLD = 240

const LeftHandColumn = (): JSX.Element => {
    const { category, isSidebarOpen } = useValues(errorTrackingIssueSceneConfigurationLogic)
    const { setCategory, openSidebar, setIsSidebarOpen } = useActions(errorTrackingIssueSceneConfigurationLogic)

    const ref = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'error-tracking-issue',
        persistent: true,
        closeThreshold: CLOSE_THRESHOLD,
        onToggleClosed: (closed) => setIsSidebarOpen(!closed),
        onDoubleClick: () => setIsSidebarOpen(!isSidebarOpen),
        placement: 'right',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { openSidePanel } = useActions(sidePanelLogic)
    const hasTasks = useFeatureFlag('TASKS')

    const style = isSidebarOpen ? { width: desiredSize ?? '30%', minWidth: CLOSE_THRESHOLD + 80 } : {}

    const comment = (
        <ButtonPrimitive
            onClick={() => openSidePanel(SidePanelTab.Discussion)}
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
                <TabsPrimitive
                    value={category}
                    onValueChange={(value) => setCategory(value as ErrorTrackingIssueSceneCategory)}
                    className="flex flex-col min-h-0"
                >
                    <div>
                        <ScrollableShadows direction="horizontal" className="border-b" hideScrollbars>
                            <TabsPrimitiveList className="flex justify-between space-x-2">
                                <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="exceptions">
                                    <IconList className="mr-1" />
                                    <span className="text-nowrap">Exceptions</span>
                                </TabsPrimitiveTrigger>
                                <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="breakdowns">
                                    <IconFilter className="mr-1" />
                                    <span className="text-nowrap">Breakdowns</span>
                                </TabsPrimitiveTrigger>
                                {hasTasks && (
                                    <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="autofix">
                                        <IconRobot className="mr-1" />
                                        <span className="text-nowrap">Autofix</span>
                                    </TabsPrimitiveTrigger>
                                )}
                                <TabsPrimitiveTrigger className="flex items-center px-2 py-1.5" value="similar_issues">
                                    <IconSearch className="mr-1" />
                                    <span className="text-nowrap">Similar issues</span>
                                </TabsPrimitiveTrigger>
                            </TabsPrimitiveList>
                        </ScrollableShadows>
                    </div>
                    <TabsPrimitiveContent value="exceptions" className="h-full min-h-0">
                        <ExceptionsTab />
                    </TabsPrimitiveContent>
                    <TabsPrimitiveContent value="breakdowns">
                        <BreakdownsSearchBar />
                        <BreakdownsChart />
                    </TabsPrimitiveContent>
                    {hasTasks && (
                        <TabsPrimitiveContent value="autofix">
                            <IssueTasks />
                        </TabsPrimitiveContent>
                    )}
                    <TabsPrimitiveContent value="similar_issues">
                        <SimilarIssuesList />
                    </TabsPrimitiveContent>
                </TabsPrimitive>
            ) : (
                <div className="flex flex-col pr-0.5">
                    <SceneBreadcrumbBackButton />
                    {comment}
                    {copyLink}
                    <LemonDivider />
                    <ButtonPrimitive onClick={() => openSidebar('overview')} iconOnly tooltip="Overview">
                        <IconWarning />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => openSidebar('exceptions')} iconOnly tooltip="Exceptions">
                        <IconList />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => openSidebar('breakdowns')} iconOnly tooltip="Breakdowns">
                        <IconFilter />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => openSidebar('autofix')} iconOnly tooltip="AI Autofix">
                        <IconRobot />
                    </ButtonPrimitive>
                    <ButtonPrimitive onClick={() => openSidebar('similar_issues')} iconOnly tooltip="Similar issues">
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
