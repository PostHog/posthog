import '../ErrorTrackingIssueScene/ErrorTrackingIssueScene.scss'

import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'
import { useRef } from 'react'

import { IconFilter, IconList, IconSearch } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconRobot } from 'lib/lemon-ui/icons'
import {
    TabsPrimitive,
    TabsPrimitiveContent,
    TabsPrimitiveList,
    TabsPrimitiveTrigger,
} from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { PostHogSDKIssueBanner } from '../../components/Banners/PostHogSDKIssueBanner'
import { BreakdownsChart } from '../../components/Breakdowns/BreakdownsChart'
import { BreakdownsSearchBar } from '../../components/Breakdowns/BreakdownsSearchBar'
import { MiniBreakdowns } from '../../components/Breakdowns/MiniBreakdowns'
import { miniBreakdownsLogic } from '../../components/Breakdowns/miniBreakdownsLogic'
import { EventsTable } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { StackTraceActions } from '../../components/ExceptionCard/Tabs/StackTraceTab/StackTraceActions'
import { StatusIndicator } from '../../components/Indicators'
import { ErrorFilters } from '../../components/IssueFilters'
import { issueFiltersLogic } from '../../components/IssueFilters/issueFiltersLogic'
import { Metadata } from '../../components/IssueMetadata'
import { IssueStatusButton } from '../../components/IssueStatusButton'
import { IssueTasks } from '../../components/IssueTasks'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { StyleVariables } from '../../components/StyleVariables'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { IssueAssigneeSelect } from './ScenePanel/IssueAssigneeSelect'
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
        <StyleVariables>
            <ErrorTrackingSetupPrompt>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }}>
                    <BindLogic logic={miniBreakdownsLogic} props={{ issueId }}>
                        {issue && (
                            <div className="flex flex-col h-[calc(var(--scene-layout-rect-height)-var(--scene-layout-header-height))]">
                                <SceneTitleSection
                                    canEdit
                                    name={issue.name}
                                    onNameChange={updateName}
                                    description={null}
                                    resourceType={{ type: 'error_tracking' }}
                                    className="px-2 h-[50px] @2xl/main-content:relative top-[0px] mt-0 mx-0"
                                    actions={
                                        <div className="flex items-center gap-1">
                                            <StatusIndicator status={issue.status} withTooltip />
                                            <IssueAssigneeSelect
                                                assignee={issue.assignee}
                                                onChange={updateAssignee}
                                                disabled={issue.status != 'active'}
                                            />
                                            <ViewRecordingsPlaylistButton
                                                filters={{
                                                    filter_group: {
                                                        type: FilterLogicalOperator.And,
                                                        values: [
                                                            {
                                                                type: FilterLogicalOperator.And,
                                                                values: [
                                                                    {
                                                                        key: '$exception_issue_id',
                                                                        type: PropertyFilterType.Event,
                                                                        operator: PropertyOperator.Exact,
                                                                        value: [issue.id],
                                                                    },
                                                                ],
                                                            },
                                                        ],
                                                    },
                                                }}
                                                size="small"
                                                type="secondary"
                                                data-attr="error-tracking-issue-view-recordings"
                                            />
                                            <IssueStatusButton status={issue.status} onChange={updateStatus} />
                                        </div>
                                    }
                                />

                                <ErrorTrackingIssueScenePanel issue={issue} />

                                <div className="ErrorTrackingIssue flex flex-grow">
                                    <div className="flex flex-1 h-full w-full">
                                        <LeftHandColumn />
                                        <RightHandColumn />
                                    </div>
                                </div>
                            </div>
                        )}
                    </BindLogic>
                </BindLogic>
            </ErrorTrackingSetupPrompt>
        </StyleVariables>
    )
}

const RightHandColumn = (): JSX.Element => {
    const { issue, issueLoading, selectedEvent, initialEventLoading } = useValues(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()

    return (
        <div className="flex flex-1 gap-y-1 overflow-y-auto min-w-[375px]">
            <PostHogSDKIssueBanner event={selectedEvent} />
            <ExceptionCard
                issueId={issue?.id ?? 'no-issue'}
                loading={issueLoading || initialEventLoading}
                event={selectedEvent ?? undefined}
                label={tagRenderer(selectedEvent)}
                renderStackTraceActions={() => {
                    return issue ? <StackTraceActions issue={issue} /> : null
                }}
            />
        </div>
    )
}

const LeftHandColumn = (): JSX.Element => {
    const { category } = useValues(errorTrackingIssueSceneConfigurationLogic)
    const { setCategory } = useActions(errorTrackingIssueSceneConfigurationLogic)

    const ref = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'error-tracking-issue',
        persistent: true,
        placement: 'right',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))
    const hasTasks = useFeatureFlag('TASKS')

    return (
        <div
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                width: desiredSize ?? '30%',
                minWidth: 320,
            }}
            className="flex flex-col h-full relative bg-surface-primary"
        >
            <TabsPrimitive
                value={category}
                onValueChange={(value) => setCategory(value as ErrorTrackingIssueSceneCategory)}
                className="flex flex-col flex-1 min-h-0"
            >
                <div>
                    <ScrollableShadows direction="horizontal" className="border-b" hideScrollbars>
                        <TabsPrimitiveList className="flex justify-between space-x-0.5">
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
                <TabsPrimitiveContent value="breakdowns" className="flex-1 min-h-0">
                    <BreakdownsTab />
                </TabsPrimitiveContent>
                {hasTasks && (
                    <TabsPrimitiveContent value="autofix">
                        <div className="p-2">
                            <IssueTasks />
                        </div>
                    </TabsPrimitiveContent>
                )}
                <TabsPrimitiveContent value="similar_issues">
                    <SimilarIssuesList />
                </TabsPrimitiveContent>
            </TabsPrimitive>

            <Resizer {...resizerLogicProps} />
        </div>
    )
}

const ExceptionsTab = (): JSX.Element => {
    const { eventsQuery, eventsQueryKey, selectedEvent } = useValues(errorTrackingIssueSceneLogic)
    const { selectEvent } = useActions(errorTrackingIssueSceneLogic)

    return (
        <div className="flex flex-col h-full">
            <div className="px-2 py-3">
                <ErrorFilters.Root>
                    <div className="flex gap-2 justify-between flex-wrap">
                        <ErrorFilters.DateRange />
                        <ErrorFilters.InternalAccounts />
                    </div>
                    <ErrorFilters.FilterGroup />
                </ErrorFilters.Root>
            </div>
            <LemonDivider className="my-0" />
            <Metadata className="flex flex-col overflow-y-auto">
                <EventsTable
                    query={eventsQuery}
                    queryKey={eventsQueryKey}
                    selectedEvent={selectedEvent}
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
const BreakdownsTab = (): JSX.Element => {
    return (
        <div className="flex flex-col h-full">
            <BreakdownsSearchBar />
            <MiniBreakdowns />
            <BreakdownsChart />
        </div>
    )
}
